import styles from "./IdeasIllustration.module.css";

// The empty results panel's picture: a draft with a spark of new ideas.
// Decorative — the empty state's title says what it means.
export default function IdeasIllustration() {
  return (
    <svg
      className={styles.art}
      viewBox="0 0 200 140"
      width={200}
      height={140}
      aria-hidden="true"
      focusable="false"
    >
      <g className={styles.rays} strokeWidth="5" strokeLinecap="round">
        <line x1="30" y1="46" x2="44" y2="54" />
        <line x1="24" y1="74" x2="40" y2="74" />
        <line x1="30" y1="102" x2="44" y2="94" />
        <line x1="170" y1="46" x2="156" y2="54" />
        <line x1="176" y1="74" x2="160" y2="74" />
        <line x1="170" y1="102" x2="156" y2="94" />
      </g>
      <rect className={styles.page} x="62" y="30" width="72" height="88" rx="12" strokeWidth="4" />
      <g className={styles.lines} strokeWidth="5" strokeLinecap="round">
        <line x1="80" y1="56" x2="116" y2="56" />
        <line x1="80" y1="72" x2="108" y2="72" />
        <line x1="80" y1="88" x2="112" y2="88" />
      </g>
      <path
        className={styles.spark}
        d="M140 8 C142 20 146 24 158 26 C146 28 142 32 140 44 C138 32 134 28 122 26 C134 24 138 20 140 8 Z"
      />
    </svg>
  );
}
