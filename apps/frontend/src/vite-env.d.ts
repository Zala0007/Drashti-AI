/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MAP_TILE_URL?: string;
  readonly VITE_MAP_LIGHT_TILE_URL?: string;
  readonly VITE_MAP_DARK_TILE_URL?: string;
  readonly VITE_MAP_ATTRIBUTION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
