import "./globals.css";
import type { Metadata } from "next";
import Providers from "@/components/Providers";
import { BRAND, TAGLINE } from "@/lib/brand";

export const metadata: Metadata = {
  title: `${BRAND} — ${TAGLINE}`,
  description: "Real-time AI meeting copilot platform — a pack for every team (Sales, and more)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
