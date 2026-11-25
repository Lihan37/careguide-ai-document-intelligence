import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'CareGuide | Document intelligence', description: 'Financial document processing, verification and review' };
export default function Layout({ children }: { children: React.ReactNode }) { return <html lang="en"><body>{children}</body></html>; }
