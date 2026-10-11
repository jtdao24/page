import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { FeatureLayer, type FeatureLayerHandle, LogoFrame } from "./featureLayers";

export type LogoSceneHandles = {
  camera: THREE.Camera;
  logo: THREE.Group;
  layers: THREE.Group[];
};

function SceneContents({ onReady }: { onReady: (handles: LogoSceneHandles) => void }) {
  const logoRef = useRef<THREE.Group>(null);
  const layerRefs = useRef<Array<FeatureLayerHandle | null>>([]);
  const { camera } = useThree();
  useEffect(() => {
    if (logoRef.current && layerRefs.current.every(Boolean)) {
      onReady({ camera, logo: logoRef.current, layers: layerRefs.current as THREE.Group[] });
    }
  }, [camera, onReady]);

  return <group ref={logoRef} scale={0.82}>
    <LogoFrame />
    {[0, 1, 2, 3, 4].map((index) => <FeatureLayer key={index} index={index} ref={(node) => { layerRefs.current[index] = node; }} />)}
  </group>;
}

export function LogoScene({ onReady, lowComplexity = false }: { onReady: (handles: LogoSceneHandles) => void; lowComplexity?: boolean }) {
  return <Canvas
    className="logo-experience-canvas"
    dpr={lowComplexity ? [1, 1.25] : [1, 1.75]}
    camera={{ position: [0, 0, 9], fov: 34, near: 0.1, far: 30 }}
    gl={{ alpha: true, antialias: !lowComplexity, powerPreference: "high-performance" }}
    shadows={!lowComplexity}
    fallback={<div className="logo-experience-fallback" role="img" aria-label="Five-layer Page architecture illustration" />}
  >
    <ambientLight intensity={1.5} />
    <directionalLight position={[4, 6, 8]} intensity={2.2} castShadow={!lowComplexity} />
    <directionalLight position={[-4, -2, 4]} intensity={0.8} color="#7fa6e3" />
    <SceneContents onReady={onReady} />
  </Canvas>;
}
