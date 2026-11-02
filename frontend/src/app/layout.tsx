import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "이두왕 | AI 퍼스널 트레이너",
  description:
    "근성장과 체중 감량을 목표로 하는 사람을 위한 AI 퍼스널 트레이너 프로젝트입니다.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body className="min-h-full antialiased">{children}</body>
    </html>
  );
}
