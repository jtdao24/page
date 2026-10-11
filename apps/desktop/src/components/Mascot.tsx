import mascot from "../assets/mascot.png";

export type MascotMood = "idle" | "thinking" | "happy";

/** Page's mascot beside the ask box: floats, thinks while Page works, and cheers when done. */
export function Mascot({ mood }: { mood: MascotMood }) {
  return <div className={`ask-mascot is-${mood}`} aria-hidden="true">
    {mood === "thinking" && <div className="mascot-thought">
      <span className="dots"><i /><i /><i /></span>
      <b className="mascot-thought-tail mascot-thought-tail-1" /><b className="mascot-thought-tail mascot-thought-tail-2" />
    </div>}
    {mood === "happy" && <div className="mascot-sparkles"><i>✦</i><i>✦</i><i>✦</i></div>}
    <img src={mascot} alt="" width={96} height={96} draggable={false} />
  </div>;
}
