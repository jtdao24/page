import { useMemo } from "react";
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

export const LOGO_WIDTH = 3.5;
export const LOGO_HEIGHT = 3.5;
export const PANEL_DEPTH = 0.12;

const layerColors = ["#222630", "#26344a", "#2c3646", "#314966", "#3d5f96"];

export function panelColor(index: number): string {
  return layerColors[index] ?? layerColors[0];
}

export function usePanelGeometry(index: number) {
  return useMemo(() => {
    const geometry = new RoundedBoxGeometry(LOGO_WIDTH, LOGO_HEIGHT, PANEL_DEPTH, 6, 0.62);
    geometry.translate((index - 2) * 0.12, (2 - index) * 0.1, 0);
    geometry.rotateZ((index - 2) * 0.045);
    return geometry;
  }, [index]);
}

export function makePanelMaterial(index: number): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    color: panelColor(index),
    roughness: 0.52,
    metalness: 0.02,
    clearcoat: 0.28,
    clearcoatRoughness: 0.4,
    transparent: true,
    opacity: index === 0 ? 0.9 : 0.64,
    side: THREE.DoubleSide,
  });
}
