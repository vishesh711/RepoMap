import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { isConfigured } from "../lib/supabase";
import { Wordmark } from "./ui";

/** The storyline from the README, drawn the way the map draws it. */
function MiniMap() {
  return (
    <svg className="minimap" viewBox="0 0 360 300" role="img" aria-label="A small code map: a route calls processOrder, which calls Inventory methods that use the Order data structure.">
      <defs>
        <marker id="mm-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M1 1.5 L9 5 L1 8.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
        </marker>
      </defs>
      <g className="mm-edges" fill="none" strokeWidth="1.5">
        <path className="mm-e fn" d="M180 50 V78" markerEnd="url(#mm-arrow)" />
        <path className="mm-e fn" d="M180 112 V130 H110 V146" markerEnd="url(#mm-arrow)" />
        <path className="mm-e fn" d="M180 112 V130 H246 V146" markerEnd="url(#mm-arrow)" />
        <path className="mm-e data" d="M170 214 V232 H120 V244" markerEnd="url(#mm-arrow)" strokeDasharray="5 3" />
        <path className="mm-e add" d="M261 180 V244" markerEnd="url(#mm-arrow)" />
      </g>
      <g className="mm-node entry"><rect x="128" y="18" width="104" height="32" rx="7" /><text x="180" y="38.5">POST /orders</text></g>
      <g className="mm-node fn"><rect x="118" y="80" width="124" height="32" rx="7" /><text x="180" y="100.5">processOrder()</text></g>
      <g className="mm-node cls">
        <rect x="60" y="148" width="240" height="66" rx="9" />
        <text x="76" y="166" className="mm-head">class Inventory</text>
        <rect x="76" y="176" width="94" height="26" rx="6" className="inner" /><text x="123" y="193.5">reserve()</text>
        <rect x="190" y="176" width="94" height="26" rx="6" className="inner new" /><text x="237" y="193.5">restock()</text>
      </g>
      <g className="mm-badge"><rect x="246" y="168" width="34" height="14" rx="4" /><text x="263" y="178.3">NEW</text></g>
      <g className="mm-node data">
        <rect x="60" y="246" width="150" height="44" rx="8" />
        <text x="74" y="263" className="mm-head">dataclass Order</text>
        <text x="74" y="280" className="mm-field">items: list[OrderItem]</text>
      </g>
      <g className="mm-node data">
        <rect x="222" y="246" width="78" height="32" rx="7" /><text x="261" y="266.5">Product</text>
      </g>
    </svg>
  );
}

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <aside className="brand">
        <Link to="/" className="brand-link" aria-label="repomap home"><Wordmark /></Link>
        <div className="brand-body">
          <h1>Read any codebase like a story.</h1>
          <p>See where code starts, what it calls and what it touches. Then see exactly what an AI change did to it.</p>
          <MiniMap />
          <ul className="points">
            <li><span><strong>11 languages</strong> and any GitHub repo</span></li>
            <li><span><strong>Diff maps</strong> for every change and PR</span></li>
            <li><span><strong>No invented links</strong>: built from the code itself</span></li>
          </ul>
        </div>
      </aside>
      <main className="panel">
        <div className="panel-top"><Link to="/" className="brand-link compact" aria-label="repomap home"><Wordmark /></Link></div>
        <div className="form-wrap">
          {!isConfigured && (
            <div className="alert info preview-note" role="status">
              <strong>Preview mode.</strong> Sign-in isn't connected to Supabase yet, so forms won't submit.
              Add your keys to <code>web/.env.local</code> (see <code>web/README.md</code>).
            </div>
          )}
          {children}
        </div>
      </main>
    </div>
  );
}
