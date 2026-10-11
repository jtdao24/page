import { useEffect, useRef, useState, type MouseEvent } from "react";
import searchImage from "../assets/folio/search.png";
import askImage from "../assets/folio/ask.png";
import graphImage from "../assets/folio/graph.png";
import homeImage from "../assets/folio/home.png";

const pages = [
  { label: "Home", title: "Make yourself at home.", src: homeImage,
    alt: "Page’s welcome screen with sample notes, vault creation, and recent vaults" },
  { label: "Graph", title: "See how your ideas belong together.", src: graphImage,
    alt: "Page’s knowledge graph connecting thesis notes, with links and backlinks beside the editor" },
  { label: "Ask", title: "A question. An answer. The sources.", src: askImage,
    alt: "Page answering a question about Copenhagen and Rotterdam, with three cited sources" },
  { label: "Search", title: "Find the thought you’re looking for.", src: searchImage,
    alt: "Page’s thesis workspace with semantic search results from PDFs and Markdown notes" },
];

export function ScreenshotFolio() {
  const [selected, setSelected] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const previewButton = useRef<HTMLButtonElement | null>(null);
  const closing = useRef(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = pages[selected];
  useEffect(() => () => { if (closeTimer.current !== null) clearTimeout(closeTimer.current); }, []);
  const setZoomOrigin = (modal: HTMLDialogElement, preview?: DOMRect) => {
    const expanded = modal.getBoundingClientRect();
    if (preview && expanded.width > 0) {
      modal.style.setProperty("--folio-zoom-x", `${preview.x + preview.width / 2 - expanded.x - expanded.width / 2}px`);
      modal.style.setProperty("--folio-zoom-y", `${preview.y + preview.height / 2 - expanded.y - expanded.height / 2}px`);
      modal.style.setProperty("--folio-zoom-scale", String(preview.width / expanded.width));
    }
  };
  const finishClose = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
    closeTimer.current = null;
    dialog.current?.close();
    dialog.current?.classList.remove("is-closing", "is-expanding");
    closing.current = false;
  };
  const close = () => {
    const modal = dialog.current;
    if (!modal?.open || closing.current) return;
    closing.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finishClose();
      return;
    }
    const transform = getComputedStyle(modal).transform;
    const opacity = getComputedStyle(modal).opacity;
    modal.classList.remove("is-expanding");
    setZoomOrigin(modal, previewButton.current?.querySelector("img")?.getBoundingClientRect());
    modal.style.setProperty("--folio-close-transform", transform);
    modal.style.setProperty("--folio-close-opacity", opacity);
    modal.classList.add("is-closing");
    // Also finish if an animation-end event is interrupted by a browser or CSS change.
    closeTimer.current = setTimeout(finishClose, 450);
  };
  const expand = (event: MouseEvent<HTMLButtonElement>) => {
    const modal = dialog.current;
    if (!modal) return;
    const preview = event.currentTarget.querySelector("img")?.getBoundingClientRect();
    previewButton.current = event.currentTarget;
    modal.classList.remove("is-expanding");
    modal.showModal();
    setZoomOrigin(modal, preview);
    modal.classList.add("is-expanding");
  };

  return <figure className="landing-art screenshot-folio" aria-label="A folio of Page app screenshots">
    <div className="folio-heading"><span>A FEW PAGES FROM PAGE</span><span>0{selected + 1} / 04</span></div>
    <div className="folio-stack">
      {pages.map((page, index) => <div key={page.label} className="folio-sheet"
        data-depth={(index - selected + pages.length) % pages.length} aria-hidden={index !== selected}>
        <div className="folio-sheet-label"><span>PAGE / {page.label.toUpperCase()}</span><span>0{index + 1}</span></div>
        <button className="folio-image-button" disabled={index !== selected} tabIndex={index === selected ? 0 : -1}
          aria-label={`Enlarge ${page.label.toLowerCase()} screenshot`} onClick={expand}>
          <img src={page.src} alt={page.alt} width={2880} height={1800}
            fetchPriority={index === 0 ? "high" : "auto"} decoding="async" />
        </button>
      </div>)}
    </div>
    <figcaption className="folio-caption">
      <p aria-live="polite">{current.title}</p>
      <div className="folio-controls" role="group" aria-label="Choose an app screenshot">
        {pages.map((page, index) => <button key={page.label} type="button" aria-pressed={selected === index}
          onClick={() => setSelected(index)}><span aria-hidden="true">0{index + 1}</span>{page.label}</button>)}
      </div>
      <span className="folio-hint">Turn a page. Take a closer look.</span>
    </figcaption>
    <dialog ref={dialog} className="folio-dialog" aria-label={`${current.label} screenshot, full size`}
      onCancel={(event) => { event.preventDefault(); close(); }}
      onAnimationEnd={(event) => { if (event.target === event.currentTarget && event.animationName === "folio-zoom-out") finishClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
      <div className="folio-dialog-content">
        <header><span>PAGE / {current.label.toUpperCase()}</span>
          <button type="button" onClick={close} aria-label="Close screenshot">Close <span aria-hidden="true">×</span></button>
        </header>
        <img src={current.src} alt={current.alt} width={2880} height={1800} />
      </div>
    </dialog>
  </figure>;
}
