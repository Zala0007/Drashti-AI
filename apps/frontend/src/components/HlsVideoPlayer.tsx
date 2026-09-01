import Hls, { ErrorTypes } from "hls.js";
import { LoaderCircle, Radio, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { safeRuntimePlaylistUrl } from "../lib/federation";

interface HlsVideoPlayerProps {
  playlistUrl?: string | null;
  cameraName: string;
}

type PlayerState = "loading" | "ready" | "playing" | "recovering" | "error" | "blocked";

export function HlsVideoPlayer({ playlistUrl, cameraName }: HlsVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const reloadAttemptRef = useRef(0);
  const [playerState, setPlayerState] = useState<PlayerState>("loading");
  const [message, setMessage] = useState("Waiting for the HLS manifest…");
  const [reloadKey, setReloadKey] = useState(0);
  const safePlaylist = useMemo(() => safeRuntimePlaylistUrl(playlistUrl), [playlistUrl]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!safePlaylist) {
      setPlayerState("blocked");
      setMessage("The runtime did not provide an allowlisted same-origin playlist.");
      return;
    }

    let hls: Hls | null = null;
    let disposed = false;
    let retryTimer: number | undefined;
    let consecutiveRecoveries = 0;
    let lastPlaybackTime = 0;
    let lastProgressAt = performance.now();
    let lastRecoveryAt = Number.NEGATIVE_INFINITY;
    setPlayerState("loading");
    setMessage("Loading the protected HLS manifest…");

    const markProgress = () => {
      lastPlaybackTime = video.currentTime;
      lastProgressAt = performance.now();
      consecutiveRecoveries = 0;
      reloadAttemptRef.current = 0;
    };

    const markPlaying = () => {
      if (disposed) return;
      markProgress();
      setPlayerState("playing");
      setMessage("Live browser delivery active");
    };

    const markReady = () => {
      if (disposed) return;
      setPlayerState("ready");
      setMessage("Live delivery ready. Select play to begin.");
    };

    const seekToLiveEdge = () => {
      const livePosition = hls?.liveSyncPosition;
      if (livePosition != null && Number.isFinite(livePosition) && livePosition - video.currentTime > 1.5) {
        video.currentTime = Math.max(0, livePosition - 0.25);
      } else if (Number.isFinite(video.duration) && video.duration - video.currentTime > 4) {
        video.currentTime = Math.max(0, video.duration - 0.5);
      }
    };

    const recoverPlayback = (reason: string) => {
      if (disposed || document.hidden) return;
      const now = performance.now();
      if (now - lastRecoveryAt < 2_500) return;
      lastRecoveryAt = now;
      consecutiveRecoveries += 1;
      setPlayerState("recovering");
      setMessage(reason);
      seekToLiveEdge();
      if (hls) {
        if (consecutiveRecoveries > 2) hls.recoverMediaError();
        hls.startLoad(-1);
      } else {
        video.load();
      }
      void video.play().catch(() => undefined);
    };

    const scheduleFullReload = (reason: string) => {
      if (disposed) return;
      setPlayerState("recovering");
      setMessage(reason);
      if (retryTimer) window.clearTimeout(retryTimer);
      const delay = Math.min(750 * (2 ** Math.min(reloadAttemptRef.current, 4)), 10_000);
      consecutiveRecoveries += 1;
      reloadAttemptRef.current += 1;
      retryTimer = window.setTimeout(() => {
        if (!disposed) setReloadKey((value) => value + 1);
      }, delay);
    };

    const markNativeError = () => scheduleFullReload("Native HLS delivery failed; reconnecting automatically…");
    const handleWaiting = () => recoverPlayback("Buffer underrun detected; catching up to live…");
    const handleStalled = () => recoverPlayback("Media delivery stalled; reconnecting automatically…");

    if (Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 5,
        maxLiveSyncPlaybackRate: 1.5,
        backBufferLength: 6,
        maxBufferLength: 12,
        maxMaxBufferLength: 20,
        maxBufferHole: 0.4,
        highBufferWatchdogPeriod: 2,
        manifestLoadingMaxRetry: 8,
        fragLoadingMaxRetry: 8,
      });
      hls.on(Hls.Events.MEDIA_ATTACHED, () => hls?.loadSource(safePlaylist));
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        setMessage("Manifest parsed; waiting for decodable media…");
        seekToLiveEdge();
        void video.play().catch(markReady);
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal || !hls) return;
        if (data.type === ErrorTypes.NETWORK_ERROR) {
          recoverPlayback("Network delivery paused; reconnecting at the live edge…");
        } else if (data.type === ErrorTypes.MEDIA_ERROR) {
          setPlayerState("recovering");
          setMessage("Recovering browser decoder at the live edge…");
          hls.recoverMediaError();
        } else {
          hls.destroy();
          hls = null;
          scheduleFullReload("The player reset after a fatal delivery error; reconnecting…");
        }
      });
      hls.attachMedia(video);
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = safePlaylist;
      video.addEventListener("loadedmetadata", markReady);
      video.addEventListener("error", markNativeError);
      video.load();
    } else {
      setPlayerState("error");
      setMessage("This browser does not provide HLS playback support.");
    }

    video.addEventListener("playing", markPlaying);
    video.addEventListener("canplay", markPlaying);
    video.addEventListener("timeupdate", markProgress);
    video.addEventListener("waiting", handleWaiting);
    video.addEventListener("stalled", handleStalled);

    const watchdogTimer = window.setInterval(() => {
      if (disposed || document.hidden || video.paused || video.ended) return;
      const now = performance.now();
      const moving = video.currentTime > lastPlaybackTime + 0.01;
      if (moving) markProgress();
      if (!moving && now - lastProgressAt > 4_000) {
        recoverPlayback("Playback watchdog detected a frozen frame; recovering…");
      }
      seekToLiveEdge();
    }, 1_500);

    const handleVisibility = () => {
      if (document.hidden) {
        hls?.stopLoad();
        return;
      }
      lastProgressAt = performance.now();
      hls?.startLoad(-1);
      seekToLiveEdge();
      void video.play().catch(markReady);
    };
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      disposed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      if (watchdogTimer) window.clearInterval(watchdogTimer);
      hls?.destroy();
      video.removeEventListener("loadedmetadata", markReady);
      video.removeEventListener("error", markNativeError);
      video.removeEventListener("playing", markPlaying);
      video.removeEventListener("canplay", markPlaying);
      video.removeEventListener("timeupdate", markProgress);
      video.removeEventListener("waiting", handleWaiting);
      video.removeEventListener("stalled", handleStalled);
      document.removeEventListener("visibilitychange", handleVisibility);
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [reloadKey, safePlaylist]);

  return (
    <div className={`live-player live-player--${playerState}`}>
      <video ref={videoRef} aria-label={`Live media for ${cameraName}`} controls muted playsInline preload="auto" />
      {!["ready", "playing"].includes(playerState) ? (
        <div className="live-player__overlay" role="status">
          {["loading", "recovering"].includes(playerState) ? <LoaderCircle className="spin" size={28} /> : <ShieldAlert size={28} />}
          <strong>{playerState === "loading" ? "Establishing browser delivery" : playerState === "recovering" ? "Recovering live delivery" : playerState === "blocked" ? "Playlist blocked" : "Playback unavailable"}</strong>
          <p>{message}</p>
          {playerState === "error" ? <button type="button" onClick={() => setReloadKey((value) => value + 1)}><RefreshCw size={14} />Reconnect now</button> : null}
        </div>
      ) : null}
      <span className="live-player__status"><Radio size={13} /><span>{message}</span></span>
    </div>
  );
}
