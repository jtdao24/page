import { useLayoutEffect } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import * as THREE from "three";
import type { LogoSceneHandles } from "./LogoScene";

if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  gsap.registerPlugin(ScrollTrigger);
}

const layerStops = [0.18, 0.36, 0.54, 0.72, 0.86];

function setLayerOpacity(layer: THREE.Group, opacity: number) {
  layer.children[0]?.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const material = object.material;
    if (Array.isArray(material)) {
      material.forEach((entry) => { entry.transparent = true; entry.opacity = opacity; });
    } else {
      material.transparent = true;
      material.opacity = opacity;
    }
  });
}

function setFeatureOpacity(layer: THREE.Group, opacity: number) {
  layer.children[1]?.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const material = object.material;
    if (Array.isArray(material)) {
      material.forEach((entry) => { entry.transparent = true; entry.opacity = opacity; });
    } else {
      material.transparent = true;
      material.opacity = opacity;
    }
  });
}

export function useLogoScrollTimeline(
  section: HTMLElement | null,
  handles: LogoSceneHandles | null,
  reducedMotion: boolean,
) {
  useLayoutEffect(() => {
    if (!section || !handles || reducedMotion) return;
    const context = gsap.context(() => {
      const camera = handles.camera as THREE.PerspectiveCamera;
      const initialZ = camera.position.z;
      camera.position.z = initialZ;
      const timeline = gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: {
          trigger: section,
          start: "top top",
          end: "bottom bottom",
          scrub: 0.7,
          pin: ".logo-experience-sticky",
          anticipatePin: 1,
          invalidateOnRefresh: true,
        },
      });

      timeline.to(handles.logo.scale, { x: 2.15, y: 2.15, z: 2.15, duration: 0.16 }, 0);
      timeline.to(camera.position, { z: -4.6, duration: 0.78 }, 0.14);
      timeline.to(handles.logo.rotation, { y: Math.PI * 0.04, duration: 0.78 }, 0.14);

      handles.layers.forEach((layer, index) => {
        const stop = layerStops[index];
        setFeatureOpacity(layer, 0);
        timeline.fromTo(layer.scale, { x: 0.88, y: 0.88, z: 0.88 }, { x: 1, y: 1, z: 1, duration: 0.05 }, stop - 0.05);
        const opacityState = { value: 0.52 };
        timeline.fromTo(opacityState, { value: 0.52 }, {
          value: 1,
          duration: 0.06,
          onUpdate: () => setLayerOpacity(layer, opacityState.value),
        }, stop - 0.05);
        const featureOpacityState = { value: 0 };
        timeline.to(featureOpacityState, {
          value: 1,
          duration: 0.07,
          onUpdate: () => setFeatureOpacity(layer, featureOpacityState.value),
        }, stop);
        if (index < handles.layers.length - 1) {
          timeline.to(opacityState, {
            value: 0.18,
            duration: 0.1,
            onUpdate: () => setLayerOpacity(layer, opacityState.value),
          }, stop + 0.09);
          timeline.to(featureOpacityState, {
            value: 0,
            duration: 0.08,
            onUpdate: () => setFeatureOpacity(layer, featureOpacityState.value),
          }, stop + 0.12);
        }
      });

      timeline.to(handles.logo.scale, { x: 1.72, y: 1.72, z: 1.72, duration: 0.12 }, 0.87);
      timeline.to(camera.position, { z: 1.5, duration: 0.12 }, 0.87);
      const cards = Array.from(section.querySelectorAll<HTMLElement>(".logo-experience-feature"));
      cards.forEach((card, index) => {
        timeline.fromTo(card, { autoAlpha: index === 0 ? 1 : 0, y: index === 0 ? 0 : 18 }, {
          autoAlpha: 1,
          y: 0,
          duration: 0.05,
        }, Math.max(0, layerStops[index] - 0.04));
        if (index < cards.length - 1) {
          timeline.to(card, { autoAlpha: 0, y: -12, duration: 0.06 }, layerStops[index] + 0.09);
        }
      });
    }, section);
    return () => context.revert();
  }, [handles, reducedMotion, section]);
}
