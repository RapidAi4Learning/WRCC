import { notFound } from "next/navigation";

import UiKit from "./UiKit";

// Development-only gallery of the shared primitives in every state: the place
// to review a restyle before it reaches a real screen. Not shipped.
export default function UiKitPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <UiKit />;
}
