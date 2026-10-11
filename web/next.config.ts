import type { NextConfig } from "next";

// The server serves the built pages itself, from files, so the interface is exported as static pages: nothing here
// may need a Node server at run time. What changes from one conversation to the next is in the query of a page's
// address and is fetched from the API, so no page has a path of its own to make.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
