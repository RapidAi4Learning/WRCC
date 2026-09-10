import styles from "./PageBackground.module.css";

// Soft petals behind the content, echoing the petals of the WRCC logo. Purely
// decorative: fixed, behind everything, and never in the way of a click.
export default function PageBackground() {
  return (
    <svg
      className={styles.background}
      viewBox="0 0 1440 1000"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <path id="wrcc-petal" d="M0 0C90-72 250-72 340 0 250 72 90 72 0 0Z" />
      </defs>
      <use href="#wrcc-petal" className={styles.purple} transform="translate(1150 -60) rotate(38) scale(1.7)" />
      <use href="#wrcc-petal" className={styles.lime} transform="translate(1330 170) rotate(82) scale(1.9)" />
      <use href="#wrcc-petal" className={styles.purple} transform="translate(1500 560) rotate(152) scale(2.1)" />
      <use href="#wrcc-petal" className={styles.purple} transform="translate(-160 1010) rotate(-32) scale(2.3)" />
      <use href="#wrcc-petal" className={styles.lime} transform="translate(860 1080) rotate(-68) scale(1.5)" />
    </svg>
  );
}
