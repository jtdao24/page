import { forwardRef, type ReactNode, useImperativeHandle, useMemo, useRef } from "react";
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { makePanelMaterial, panelColor, usePanelGeometry } from "./logoGeometry";

export type FeatureLayerHandle = THREE.Group;

type Point = [number, number];

function Dot({ position, color = "#7fa6e3", size = 0.12 }: { position: Point; color?: string; size?: number }) {
  return <mesh position={[position[0], position[1], 0.14]}>
    <sphereGeometry args={[size, 12, 8]} />
    <meshBasicMaterial color={color} />
  </mesh>;
}

function MarkdownContent() {
  return <group position={[-1.55, 0.8, 0.14]}>
    <mesh position={[1.45, 0.72, 0]}><boxGeometry args={[2.65, 0.08, 0.03]} /><meshBasicMaterial color="#7fa6e3" /></mesh>
    {[0, 1, 2, 3, 4].map((line) => <mesh key={line} position={[1.18, 0.28 - line * 0.27, 0]}><boxGeometry args={[2.2 - (line % 2) * 0.42, 0.045, 0.025]} /><meshBasicMaterial color="#bcc5d2" transparent opacity={0.72} /></mesh>)}
    <mesh position={[1.35, -1.2, 0]}><boxGeometry args={[1.2, 0.08, 0.03]} /><meshBasicMaterial color="#9dbcf0" /></mesh>
    <mesh position={[2.45, -1.2, 0]}><boxGeometry args={[0.55, 0.08, 0.03]} /><meshBasicMaterial color="#8f96a3" /></mesh>
  </group>;
}

function GraphContent() {
  const points: Point[] = [[-1.7, 0.95], [0, 1.45], [1.65, 0.7], [-0.85, -0.8], [1.15, -1.15]];
  return <group>
    {points.map((point, index) => <Dot key={index} position={point} size={index === 1 ? 0.18 : 0.12} />)}
  </group>;
}

function SearchContent() {
  return <group position={[0, 0.5, 0.14]}>
    <mesh><boxGeometry args={[3.75, 0.48, 0.04]} /><meshBasicMaterial color="#191c22" transparent opacity={0.92} /></mesh>
    <mesh position={[-1.05, 0, 0.03]}><boxGeometry args={[1.65, 0.06, 0.03]} /><meshBasicMaterial color="#7fa6e3" /></mesh>
    {[0, 1, 2].map((row) => <group key={row} position={[0, -0.75 - row * 0.48, 0]}>
      <mesh position={[-1.05, 0, 0]}><boxGeometry args={[0.38, 0.18, 0.03]} /><meshBasicMaterial color={row === 0 ? "#7fa6e3" : "#8f96a3"} /></mesh>
      <mesh position={[0.82, 0.04, 0]}><boxGeometry args={[2.0 - row * 0.25, 0.055, 0.03]} /><meshBasicMaterial color="#bcc5d2" transparent opacity={0.72} /></mesh>
      <mesh position={[0.52, -0.14, 0]}><boxGeometry args={[1.4, 0.035, 0.03]} /><meshBasicMaterial color="#8f96a3" transparent opacity={0.7} /></mesh>
    </group>)}
  </group>;
}

function RankingContent() {
  return <group position={[-1.65, 0, 0.14]}>
    {[0, 1, 2, 3].map((row) => <group key={row} position={[0, 1.15 - row * 0.72, 0]}>
      <mesh position={[0.18, 0, 0]}><boxGeometry args={[2.85, 0.3, 0.04]} /><meshBasicMaterial color="#191c22" transparent opacity={0.82} /></mesh>
      <mesh position={[-0.98 + row * 0.22, 0, 0.04]}><boxGeometry args={[0.25 + (3 - row) * 0.32, 0.16, 0.03]} /><meshBasicMaterial color={row < 2 ? "#7fa6e3" : "#8f96a3"} /></mesh>
    </group>)}
  </group>;
}

function ContextContent() {
  return <group position={[-1.65, 0, 0.14]}>
    <mesh position={[1.55, 0, -0.01]}><boxGeometry args={[3.35, 3.15, 0.05]} /><meshBasicMaterial color="#191c22" transparent opacity={0.8} /></mesh>
    {[0, 1, 2, 3, 4].map((line) => <mesh key={line} position={[1.5, 1.05 - line * 0.42, 0.05]}><boxGeometry args={[2.45 - (line % 2) * 0.4, 0.08, 0.03]} /><meshBasicMaterial color={line < 3 ? "#7fa6e3" : "#8f96a3"} transparent opacity={line < 3 ? 0.9 : 0.55} /></mesh>)}
    <mesh position={[1.55, -1.22, 0.06]}><boxGeometry args={[2.1, 0.22, 0.04]} /><meshBasicMaterial color="#26344a" /></mesh>
  </group>;
}

const content: ReactNode[] = [<MarkdownContent key="markdown" />, <GraphContent key="graph" />, <SearchContent key="search" />, <RankingContent key="ranking" />, <ContextContent key="context" />];

export const FeatureLayer = forwardRef<FeatureLayerHandle, { index: number }>(function FeatureLayer({ index }, ref) {
  const groupRef = useRef<THREE.Group>(null);
  const contentRef = useRef<THREE.Group>(null);
  const geometry = usePanelGeometry(index);
  const material = useMemo(() => makePanelMaterial(index), [index]);
  useImperativeHandle(ref, () => groupRef.current!, []);
  return <group ref={groupRef} position={[0, 0, (2 - index) * 0.72]} rotation={[0, 0, (index - 2) * 0.045]}>
    <mesh geometry={geometry} castShadow receiveShadow>
      <primitive object={material} attach="material" />
    </mesh>
    <group ref={contentRef}>{content[index]}</group>
  </group>;
});

FeatureLayer.displayName = "FeatureLayer";

export function LogoFrame() {
  const geometry = useMemo(() => new RoundedBoxGeometry(5, 5, 0.28, 5, 0.7), []);
  return <group>
    <mesh position={[0, 0, -2.25]} scale={[1.08, 1.08, 1]}>
      <primitive object={geometry} />
      <meshPhysicalMaterial color={panelColor(4)} roughness={0.62} metalness={0.01} clearcoat={0.2} transparent opacity={0.92} />
    </mesh>
  </group>;
}
