import "./globals.css";

export const metadata = {
  title: "Memory Agent",
  description: "ChatGPT-style agent with a memory architecture backend",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
