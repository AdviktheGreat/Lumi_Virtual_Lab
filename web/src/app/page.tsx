import { Suspense } from "react";
import { HomeView } from "@/components/home-view";

// What the program is to be begun as may be named in the address's query, which is how a link from another page begins one
export default function Home() {
  return (
    <Suspense>
      <HomeView />
    </Suspense>
  );
}
