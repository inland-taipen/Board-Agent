import { useEffect, useState } from "react";

import { api, type Citation } from "../api";

interface Props {
  packId: string;
  chunkId: string;
  onClose: () => void;
}

/**
 * The audit trail, made usable.
 *
 * The BRD requires a link from every briefing statement to its source page.
 * Showing the citation label alone would satisfy that on paper; opening the
 * exact passage is what lets a director actually check a finding in the ninety
 * seconds they have before the item is called.
 */
export default function SourceDrawer({ packId, chunkId, onClose }: Props) {
  const [passage, setPassage] = useState<(Citation & { text: string }) | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setPassage(null);
    setError("");

    api
      .sourcePassage(packId, chunkId)
      .then((result) => {
        if (!cancelled) setPassage(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });

    return () => {
      cancelled = true;
    };
  }, [packId, chunkId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="drawer-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Source passage"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <button className="close" onClick={onClose} aria-label="Close">
            ×
          </button>
          <h2>{passage?.document ?? "Source passage"}</h2>
          <div className="meta">
            {passage ? (
              <>
                {passage.locator} · reference {passage.chunk_id}
              </>
            ) : (
              `Reference ${chunkId}`
            )}
          </div>
        </header>

        {error ? (
          <div className="banner error" style={{ margin: 22 }}>
            {error}
          </div>
        ) : passage ? (
          <div className="passage">{passage.text}</div>
        ) : (
          <div className="progress" style={{ padding: 22 }}>
            <span className="spinner" /> Opening the source page...
          </div>
        )}
      </aside>
    </div>
  );
}
