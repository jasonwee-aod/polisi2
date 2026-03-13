import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Outfit } from "next/font/google";

import "./globals.css";

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-primary",
  display: "swap"
});

export const metadata: Metadata = {
  title: "Polisi.ai",
  description: "Grounded Malaysian policy answers with citations."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={outfit.variable} style={{ height: "100%" }}>
      <body style={{ height: "100%" }}>{children}</body>
    </html>
  );
}
