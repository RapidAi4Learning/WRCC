import type { MetadataRoute } from "next";

// Lets the studio be installed to a phone's home screen or a desktop dock
// with its own icon, opening straight on the compose screen.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "WRCC Social Media Marketing",
    short_name: "WRCC Social",
    description:
      "Social content generation and course catalog studio for Western Riverina Community College.",
    start_url: "/generate",
    display: "standalone",
    background_color: "#f8f5fb",
    theme_color: "#582281",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icons/maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
