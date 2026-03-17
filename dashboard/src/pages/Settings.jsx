import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchModels, fetchConfig, updateConfig } from "../api/ollama";

export default function Settings() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: fetchModels });
  const config = useQuery({ queryKey: ["config"], queryFn: fetchConfig });

  const [selectedModel, setSelectedModel] = useState("");
  const [autoReview, setAutoReview] = useState(false);
  const [autoDescribe, setAutoDescribe] = useState(false);
  const [autoImprove, setAutoImprove] = useState(false);
  const [customInstructions, setCustomInstructions] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (config.data?.config) {
      const c = config.data.config;
      // TOML structure: [config] section has model, [pr_reviewer] has settings
      setSelectedModel(c.config?.model || "");
      const cmds = c.gitlab?.pr_commands || c.gitea?.pr_commands || [];
      setAutoReview(cmds.includes("/review"));
      setAutoDescribe(cmds.includes("/describe"));
      setAutoImprove(cmds.includes("/improve"));
      setCustomInstructions(c.config?.custom_instructions || "");
    }
  }, [config.data]);

  const mutation = useMutation({
    mutationFn: (cfg) => updateConfig(cfg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const handleSave = () => {
    // Rebuild the TOML structure
    const currentConfig = config.data?.config || {};
    const prCommands = [
      ...(autoDescribe ? ["/describe"] : []),
      ...(autoReview ? ["/review"] : []),
      ...(autoImprove ? ["/improve"] : []),
    ];
    mutation.mutate({
      ...currentConfig,
      config: {
        ...currentConfig.config,
        model: selectedModel,
        custom_instructions: customInstructions,
      },
      gitlab: { ...currentConfig.gitlab, pr_commands: prCommands },
      gitea: { ...currentConfig.gitea, pr_commands: prCommands },
    });
  };

  return (
    <div className="space-y-8 max-w-2xl">
      <h2 className="text-2xl font-bold text-white">Settings</h2>

      {/* Model Selection */}
      <section className="space-y-2">
        <label className="block text-sm font-medium text-gray-400">LLM Model</label>
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="w-full bg-panel border border-border rounded-lg px-3 py-2.5 text-sm text-gray-300 focus:outline-none focus:border-indigo-500"
        >
          <option value="">Select a model...</option>
          {models.data?.models?.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} {m.size ? `(${m.size})` : ""}
            </option>
          ))}
        </select>
        {models.isLoading && <p className="text-xs text-gray-500">Loading models...</p>}
      </section>

      {/* Auto Commands */}
      <section className="space-y-3">
        <label className="block text-sm font-medium text-gray-400">Auto Commands</label>
        <div className="space-y-2">
          {[
            { label: "Auto Review", value: autoReview, setter: setAutoReview },
            { label: "Auto Describe", value: autoDescribe, setter: setAutoDescribe },
            { label: "Auto Improve", value: autoImprove, setter: setAutoImprove },
          ].map(({ label, value, setter }) => (
            <label key={label} className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => setter(e.target.checked)}
                className="w-4 h-4 rounded border-border bg-panel text-indigo-500 focus:ring-indigo-500 focus:ring-offset-0"
              />
              <span className="text-sm text-gray-300">{label}</span>
            </label>
          ))}
        </div>
      </section>

      {/* Custom Instructions */}
      <section className="space-y-2">
        <label className="block text-sm font-medium text-gray-400">Custom Instructions</label>
        <textarea
          value={customInstructions}
          onChange={(e) => setCustomInstructions(e.target.value)}
          rows={6}
          placeholder="Add custom review instructions for the LLM..."
          className="w-full bg-panel border border-border rounded-lg px-3 py-2.5 text-sm text-gray-300 placeholder-gray-600 focus:outline-none focus:border-indigo-500 resize-y"
        />
      </section>

      {/* Save */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={mutation.isPending}
          className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        >
          {mutation.isPending ? "Saving..." : "Save Settings"}
        </button>
        {saved && <span className="text-sm text-emerald-400">Settings saved.</span>}
        {mutation.isError && <span className="text-sm text-red-400">Failed to save.</span>}
      </div>
    </div>
  );
}
