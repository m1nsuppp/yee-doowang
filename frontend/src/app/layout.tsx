import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "이두왕 | PushDay 채팅",
  description: "PushDay 운동 후보를 대화로 추천합니다.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body className="min-h-full antialiased">{children}</body>
    </html>
  );
}
