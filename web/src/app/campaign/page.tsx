"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { CampaignNotFound, CampaignView } from "@/components/campaign-view";

// A campaign is named in the address's query, as a conversation is, because the pages are exported as they are
function Campaign() {
  const id = useSearchParams().get("id");

  return id ? <CampaignView key={id} id={id} /> : <CampaignNotFound />;
}

export default function CampaignPage() {
  return (
    <Suspense>
      <Campaign />
    </Suspense>
  );
}
