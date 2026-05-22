// audiobuilder/src/utils/pipelineFile.ts
// Utilities for saving and loading pipeline YAML files from the browser.

/**
 * Trigger a browser download of the given YAML string as a .yaml file.
 */
export function downloadYAML(yamlStr: string, filename = "pipeline.yaml"): void {
  const blob = new Blob([yamlStr], { type: "text/yaml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Open a file picker and return the text content of the selected file.
 * Resolves with null if the user cancels.
 */
export function openYAMLFile(): Promise<string | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".yaml,.yml";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) {
        resolve(null);
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => resolve(null);
      reader.readAsText(file);
    };
    // Resolve null if the dialog is dismissed without selecting a file
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}
