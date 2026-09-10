/** Join class names, dropping the falsy ones (`cx("a", isOn && "b")`). */
export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
