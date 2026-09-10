import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

export interface PageHeaderProps {
  title: ReactNode;
  lede?: ReactNode;
  /** Page-level controls, aligned to the right of the title on wide screens. */
  actions?: ReactNode;
  /** Id for the h1, for a region that is `aria-labelledby` it. */
  titleId?: string;
}

/** The h1 + one-line explanation every screen opens with. */
export default function PageHeader({ title, lede, actions, titleId }: PageHeaderProps) {
  return (
    <header className={styles.header}>
      <div>
        <h1 id={titleId} className={styles.title}>
          {title}
        </h1>
        {lede ? <p className={styles.lede}>{lede}</p> : null}
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
  );
}
