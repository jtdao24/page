import { useEffect, useRef, useState } from "react";
import mascot from "../assets/mascot-sitting.png";

/** Page's mascot sitting against the side of the download card. It sways, and waves once when the card scrolls into view. */
export function CardMascot() {
  const ref = useRef<HTMLDivElement>(null);
  const [waving, setWaving] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) { setWaving(true); observer.disconnect(); }
    }, { threshold: 0.9 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return <div ref={ref} className={`card-mascot${waving ? " is-waving" : ""}`} aria-hidden="true">
    <img src={mascot} alt="" width={190} height={190} draggable={false} onAnimationEnd={() => setWaving(false)} />
  </div>;
}
