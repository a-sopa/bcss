import { lazy, Suspense } from "react";
import { MotionConfig } from "motion/react";
import { Header } from "./components/Header";
import { Hero } from "./components/Hero";
import { Footer } from "./components/Footer";
import { Overview } from "./sections/Overview";
import { Capabilities } from "./sections/Capabilities";
import { Architecture } from "./sections/Architecture";
import { Europe } from "./sections/Europe";
import { Security } from "./sections/Security";
import { Docs } from "./sections/Docs";
import { FinalCta } from "./sections/FinalCta";
import { Migration } from "./sections/Migration";
import { Console } from "./console/Console";
import { useHashRoute } from "./hooks/useHashRoute";
import { AuthGate } from "./console/AuthGate";

const EditorPage = lazy(() => import("./editor/EditorPage"));

export function App() {
  const route = useHashRoute();
  if (route.name !== "home") {
    return (
      <MotionConfig reducedMotion="user">
        <AuthGate>
          {route.name === "editor" ? (
            <Suspense fallback={<div className="min-h-screen" />}>
              <EditorPage key={route.appId} appId={route.appId} />
            </Suspense>
          ) : (
            <Console />
          )}
        </AuthGate>
      </MotionConfig>
    );
  }
  return (
    <MotionConfig reducedMotion="user">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-full focus:bg-teal focus:px-4 focus:py-2 focus:text-navy-950"
      >
        Skip to content
      </a>
      <Header />
      <main id="main">
        <Hero />
        <Overview />
        <Capabilities />
        <Migration />
        <Architecture />
        <Europe />
        <Security />
        <Docs />
        <FinalCta />
      </main>
      <Footer />
    </MotionConfig>
  );
}
