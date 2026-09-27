import { NotBuilt } from "@/components/not-built";

export default function ModelsPage() {
  return (
    <NotBuilt
      title="Models"
      phase={3}
      what="Extraction accuracy, cost per document and latency across models and prompt versions."
    />
  );
}
