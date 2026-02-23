import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Redthread - Financial Crime Investigation",
  description:
    "AI-assisted investigation workspace for BSA/AML analysts. Entity resolution, OFAC screening, evidence tracking, and SAR narrative generation.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
