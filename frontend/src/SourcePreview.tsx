import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Minus,
  Plus,
  LocateFixed,
  AlertCircle,
} from "lucide-react";
import {
  getDocument,
  GlobalWorkerOptions,
  Util,
  type PDFDocumentProxy,
  type RenderTask,
} from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { Evidence, Office, Source } from "./types";
import { Loading } from "./components";
import { locatePassage, savedSourcePassage } from "./sourceLocation";

GlobalWorkerOptions.workerSrc = workerUrl;
type Highlight = {
  left: number;
  top: number;
  width: number;
  height: number;
  angle: number;
};

export default function SourcePreview({
  office,
  evidence,
  source,
  pageNumber,
  zoom,
  onPageChange,
  onZoomChange,
}: {
  office: Office;
  evidence?: Pick<Evidence, "source_id" | "quote" | "page" | "section">;
  source?: Source;
  pageNumber: number;
  zoom: number;
  onPageChange: (page: number) => void;
  onZoomChange: (zoom: number) => void;
}) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [saved, setSaved] = useState<ReturnType<
    typeof savedSourcePassage
  > | null>(null);
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState("");
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [ambiguous, setAmbiguous] = useState(false);
  const [pageText, setPageText] = useState("");
  const [width, setWidth] = useState(600);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const scroll = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const cited = useRef<HTMLElement>(null);
  const onPage = useRef(onPageChange);
  onPage.current = onPageChange;
  const sourceId = evidence?.source_id || source?.source_id;

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let task: ReturnType<typeof getDocument> | undefined;
    setLoading(true);
    setError("");
    setDocument(null);
    setSaved(null);
    async function load() {
      try {
        if (!sourceId) throw new Error("Source metadata is unavailable.");
        const response = await fetch(
          `/api/${office}/sources/${encodeURIComponent(sourceId)}/content`,
          { signal: controller.signal },
        );
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(
            body?.error?.message || "The original source could not be opened.",
          );
        }
        if (
          source?.source_type === "slack" ||
          response.headers.get("content-type")?.includes("json")
        ) {
          const passage = savedSourcePassage(
            await response.text(),
            evidence?.quote || "",
          );
          if (!disposed) {
            setSaved(passage);
            setLoading(false);
          }
        } else {
          const bytes = new Uint8Array(await response.arrayBuffer());
          if (disposed) return;
          task = getDocument({
            data: bytes,
            cMapUrl: "/pdfjs/cmaps/",
            cMapPacked: true,
            standardFontDataUrl: "/pdfjs/standard_fonts/",
            wasmUrl: "/pdfjs/wasm/",
          });
          const pdf = await task.promise;
          if (!disposed) {
            setDocument(pdf);
            setLoading(false);
          }
        }
      } catch (error) {
        if (!disposed) {
          setError(
            error instanceof Error
              ? error.message
              : "The original source could not be opened.",
          );
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      disposed = true;
      controller.abort();
      void task?.destroy();
    };
  }, [office, sourceId, evidence?.quote, source?.source_type]);

  useEffect(() => {
    const element = scroll.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setWidth(Math.max(180, element.clientWidth - 24)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [loading]);

  useEffect(() => {
    if (!document) return;
    let cancelled = false;
    let render: RenderTask | undefined;
    setRendering(true);
    setError("");
    setHighlights([]);
    setPageText("");
    const pageIndex = Math.min(document.numPages, Math.max(1, pageNumber));
    if (pageIndex !== pageNumber) onPage.current(pageIndex);
    async function paint() {
      try {
        const page = await document!.getPage(pageIndex);
        if (cancelled || !canvas.current) return;
        const original = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({
          scale: ((width / original.width) * zoom) / 100,
        });
        // Render into a separate canvas so a resize/page change can cancel safely.
        const element = window.document.createElement("canvas");
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        element.width = Math.ceil(viewport.width * dpr);
        element.height = Math.ceil(viewport.height * dpr);
        element.style.width = `${viewport.width}px`;
        element.style.height = `${viewport.height}px`;
        setSize({ width: viewport.width, height: viewport.height });
        render = page.render({
          canvas: element,
          viewport,
          transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
        });
        const [content] = await Promise.all([
          page.getTextContent(),
          render.promise,
        ]);
        if (cancelled || !canvas.current) return;
        canvas.current.width = element.width;
        canvas.current.height = element.height;
        canvas.current.style.width = `${viewport.width}px`;
        canvas.current.style.height = `${viewport.height}px`;
        canvas.current.getContext("2d")!.drawImage(element, 0, 0);
        const items = content.items.filter(
          (item): item is TextItem => "str" in item,
        );
        const match =
          evidence && pageIndex === evidence.page
            ? locatePassage(items, evidence.quote)
            : { indices: [], ambiguous: false };
        const boxes = match.indices.map((index) => {
          const item = items[index];
          const matrix = Util.transform(viewport.transform, item.transform);
          const height = Math.hypot(matrix[2], matrix[3]);
          const ascent = content.styles[item.fontName]?.ascent ?? 0.85;
          return {
            left: matrix[4],
            top: matrix[5] - height * ascent,
            width: Math.max(1, item.width * viewport.scale),
            height: height * 1.15,
            angle: Math.atan2(matrix[1], matrix[0]),
          };
        });
        setHighlights(boxes);
        setAmbiguous(match.ambiguous);
        setPageText(
          items.map((item) => item.str + (item.hasEOL ? "\n" : " ")).join(""),
        );
        setRendering(false);
        requestAnimationFrame(() => {
          if (!cancelled && scroll.current)
            scroll.current.scrollTop = Math.max(
              0,
              (boxes[0]?.top || 0) - scroll.current.clientHeight / 3,
            );
        });
      } catch (error) {
        if (!cancelled) {
          setError(
            error instanceof Error
              ? error.message
              : "This PDF page could not be rendered.",
          );
          setRendering(false);
        }
      }
    }
    void paint();
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [document, pageNumber, width, zoom, evidence?.page, evidence?.quote]);

  useEffect(() => {
    if (saved && cited.current && scroll.current)
      scroll.current.scrollTop = Math.max(
        0,
        cited.current.offsetTop - scroll.current.offsetTop - 30,
      );
  }, [saved]);

  if (loading) return <Loading label="Loading original source…" />;
  if (error)
    return (
      <div className="notice warning" role="alert">
        <AlertCircle size={17} />
        <span>{error} You can still download the original file.</span>
      </div>
    );
  if (saved)
    return (
      <section
        className="saved-source"
        aria-label="Original saved Slack source"
      >
        <p className="source-location-note">
          Saved Slack event ·{" "}
          {!evidence ? "Original messages" : saved.start >= 0
            ? "Cited message highlighted"
            : "The cited quote could not be located in this saved source"}
        </p>
        <div className="source-page-scroll saved-source-scroll" ref={scroll}>
          <pre>
            {!evidence || saved.start < 0 ? (
              saved.text
            ) : (
              <>
                {saved.text.slice(0, saved.start)}
                <mark ref={cited}>
                  {saved.text.slice(saved.start, saved.end)}
                </mark>
                {saved.text.slice(saved.end)}
              </>
            )}
          </pre>
        </div>
      </section>
    );
  if (!document) return null;
  return (
    <section className="pdf-source" aria-label="Original PDF source">
      <div className="pdf-toolbar">
        <div>
          <button
            className="icon-button"
            aria-label="Previous source page"
            disabled={pageNumber <= 1}
            onClick={() => onPageChange(pageNumber - 1)}
          >
            <ChevronLeft size={17} />
          </button>
          <span>
            Page {pageNumber} of {document.numPages}
          </span>
          <button
            className="icon-button"
            aria-label="Next source page"
            disabled={pageNumber >= document.numPages}
            onClick={() => onPageChange(pageNumber + 1)}
          >
            <ChevronRight size={17} />
          </button>
        </div>
        {evidence && <button
          className="text-button"
          onClick={() => {
            if (pageNumber !== evidence.page) onPageChange(evidence.page);
            else if (scroll.current)
              scroll.current.scrollTop = Math.max(
                0,
                (highlights[0]?.top || 0) - scroll.current.clientHeight / 3,
              );
          }}
        >
          <LocateFixed size={15} />
          Cited page {evidence.page}
          {evidence.section ? ` · § ${evidence.section}` : ""}
        </button>}
        <div>
          <button
            className="icon-button"
            aria-label="Zoom out"
            disabled={zoom <= 50}
            onClick={() => onZoomChange(zoom - 25)}
          >
            <Minus size={15} />
          </button>
          <span>{zoom}%</span>
          <button
            className="icon-button"
            aria-label="Zoom in"
            disabled={zoom >= 200}
            onClick={() => onZoomChange(zoom + 25)}
          >
            <Plus size={15} />
          </button>
        </div>
      </div>
      <p className="source-location-note" role="status">
        {rendering
          ? "Rendering page…"
          : !evidence ? "Original PDF · use page controls to inspect the document."
          : highlights.length
            ? "Highlighted lines contain the cited passage."
            : ambiguous
              ? "More than one matching passage is present on this page; no location has been guessed."
              : pageNumber !== evidence.page
                ? `The citation is on page ${evidence.page}.`
                : "The quote could not be located on this page. Compare the preserved evidence and original."}
      </p>
      <div
        ref={scroll}
        className="source-page-scroll"
        aria-busy={rendering}
        tabIndex={0}
        aria-label="PDF page; use arrow keys to scroll"
      >
        <div
          className="pdf-page"
          style={{ width: size.width, height: size.height }}
        >
          <canvas
            ref={canvas}
            role="img"
            aria-label={`Original PDF page ${pageNumber}${evidence?.section ? `; cited section ${evidence.section}` : ""}`}
          />
          {highlights.map((box, index) => (
            <span
              key={index}
              className="pdf-passage-highlight"
              aria-hidden="true"
              style={{
                left: box.left,
                top: box.top,
                width: box.width,
                height: box.height,
                transform: `rotate(${box.angle}rad)`,
              }}
            />
          ))}
        </div>
      </div>
      <details className="pdf-page-text">
        <summary>Readable text from this page</summary>
        <pre>{pageText}</pre>
      </details>
    </section>
  );
}
