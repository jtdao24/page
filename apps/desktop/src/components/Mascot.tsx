import mascot from "../assets/mascot.png";

export type MascotMood = "idle" | "thinking" | "happy";

/**
 * Page's mascot, sitting on top of the chat: on the answer card when it's open,
 * otherwise on the ask box. Its legs tuck behind the edge it sits on. It sways
 * while idle, shows a thought bubble while Page works, and dances when done.
 */
export function Mascot({ mood }: { mood: MascotMood }) {
  return <div className={`ask-mascot is-${mood}`} aria-hidden="true">
    {mood === "thinking" && <div className="mascot-thought">
      <span className="dots"><i /><i /><i /></span>
      <b className="mascot-thought-tail mascot-thought-tail-1" /><b className="mascot-thought-tail mascot-thought-tail-2" />
    </div>}
    {mood === "happy" && <div className="mascot-sparkles"><i>♪</i><i>✦</i><i>♫</i><i>✦</i></div>}
    <img src={mascot} alt="" width={96} height={96} draggable={false} />
  </div>;
}
