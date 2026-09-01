import {
  createElementObject,
  createLayerComponent,
  extendContext,
  type LeafletContextInterface,
} from "@react-leaflet/core";
import L from "leaflet";
import "leaflet.markercluster";
import type { PropsWithChildren } from "react";

export type MarkerClusterLayerProps = PropsWithChildren<L.MarkerClusterGroupOptions>;

/**
 * React-Leaflet bridge for Leaflet.markercluster.
 *
 * Keeping this adapter local avoids the CommonJS default-export ambiguity of
 * third-party React wrappers and makes the Leaflet layer/container lifecycle
 * explicit. Child Markers are mounted directly into the cluster group.
 */
function createMarkerClusterLayer(
  props: MarkerClusterLayerProps,
  context: LeafletContextInterface,
) {
  const options = { ...props };
  delete options.children;
  const instance = L.markerClusterGroup(options);
  return createElementObject(
    instance,
    extendContext(context, { layerContainer: instance }),
  );
}

export const MarkerClusterLayer = createLayerComponent<
  L.MarkerClusterGroup,
  MarkerClusterLayerProps
>(createMarkerClusterLayer);
