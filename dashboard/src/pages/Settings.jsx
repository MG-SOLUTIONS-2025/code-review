import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchModels, fetchConfig, updateConfig, fetchHealth, fetchPrompts, fetchPrompt, updatePrompt } from "../api/llm";

export default function Settings() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: fetchModels });
  const config = useQuery({ queryKey: ["config"], queryFn: fetchConfig });
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const promptsList = useQuery({ queryKey: ["prompts"], queryFn: fetchPrompts });

  const [selectedModel, setSelectedModel] = useState("");
  const [autoReview, setAutoReview] = useState(false);
  const [autoDescribe, setAutoDescribe] = useState(false);
  const [autoImprove, setAutoImprove] = useState(false);
  const [customInstructions, setCustomInstructions] = useState("");
  const [saved, setSaved] = useState(false);

  // Prompt editor state
  const [activePromptTab, setActivePromptTab] = useState(null);
  const [promptContent, setPromptContent] = useState("");
  const [promptSaved, setPromptSaved] = useState(false);

  const engineInfo = health.data?.services?.llm;

  useEffect(() => {
    if (config.data?.config) {
      const cfg = config.data?.config || {};
      setSelectedModel(cfg.config?.model || "");
      const cmds = cfg.gitlab?.pr_commands || cfg.gitea?.pr_commands || [];
      setAutoReview(cmds.includes("/review"));
      setAutoDescribe(cmds.includes("/describe"));
      setAutoImprove(cmds.includes("/improve"));
      setCustomInstructions(cfg.config?.custom_instructions || "");
    }
  }, [config.data]);

  // Load prompt content when tab changes
  useEffect(() => {
    if (activePromptTab) {
      fetchPrompt(activePromptTab).then((data) => {
        setPromptContent(data.content);
      });
    }
  }, [activePromptTab]);

  // Auto-select first prompt tab
  useEffect(() => {
    if (promptsList.data?.prompts?.length && !activePromptTab) {
      setActivePromptTab(promptsList.data.prompts[0].name);
    }
  }, [promptsList.data, activePromptTab]);

  const configMutation = useMutation({
    mutationFn: (cfg) => updateConfig(cfg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const promptMutation = useMutation({
    mutationFn: ({ name, content }) => updatePrompt(name, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setPromptSaved(true);
      setTimeout(() => setPromptSaved(false), 2000);
    },
  });

  const handleSave = () => {
    const cfg = config.data?.config || {};
    const currentConfig = cfg;
    const prCommands = [
      ...(autoDescribe ? ["/describe"] : []),
      ...(autoReview ? ["/review"] : []),
      ...(autoImprove ? ["/improve"] : []),
    ];
    configMutation.mutate({
      ...currentConfig,
      config: {
        ...currentConfig.config,
        model: selectedModel,
        custom_instructions: customInstructions,
      },
      gitlab: { ...(currentConfig.gitlab || {}), pr_commands: prCommands },
      gitea: { ...(currentConfig.gitea || {}), pr_commands: prCommands },
    });
  };

  const handlePromptSave = () => {
    if (activePromptTab) {
      promptMutation.mutate({ name: activePromptTab, content: promptContent });
    }
  };

  return (
    <div className="space-y-8 max-w-2xl">
      <h2 className="text-2xl font-bold text-white">Settings</h2>

      {/* Inference Engine Badge */}
      {engineInfo && (
        <section className="space-y-2">
          <label className="block text-sm font-medium text-gray-400">Inference Engine</label>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-panel border border-border text-sm text-gray-300">
              <span className={`w-2 h-2 rounded-full ${engineInfo.status === "healthy" ? "bg-emerald-400" : "bg-red-400"}`} />
              {engineInfo.engine?.toUpperCase() || "Unknown"}
            </span>
            {engineInfo.model && (
              <span className="text-xs text-gray-500">Model: {engineInfo.model}</span>
            )}
          </div>
        </section>
      )}

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
            <option key={m.name || m.id} value={m.name || m.id}>
              {m.name || m.id} {m.size ? `(${m.size})` : ""}
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

      {/* Save Config */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={configMutation.isPending}
          className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        >
          {configMutation.isPending ? "Saving..." : "Save Settings"}
        </button>
        {saved && <span className="text-sm text-emerald-400">Settings saved.</span>}
        {configMutation.isError && <span className="text-sm text-red-400">Failed to save.</span>}
      </div>

      {/* Prompt Template Editor */}
      <section className="space-y-3 pt-4 border-t border-border">
        <label className="block text-sm font-medium text-gray-400">Prompt Templates</label>
        {promptsList.isLoading && <p className="text-xs text-gray-500">Loading prompts...</p>}

        {promptsList.data?.prompts?.length > 0 && (
          <>
            {/* Tabs */}
            <div className="flex gap-1 border-b border-border">
              {promptsList.data.prompts.map((p) => (
                <button
                  key={p.name}
                  onClick={() => setActivePromptTab(p.name)}
                  className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                    activePromptTab === p.name
                      ? "bg-panel border border-b-0 border-border text-white"
                      : "text-gray-500 hover:text-gray-300"
                  }`}
                >
                  {p.name}
                </button>
              ))}
            </div>

            {/* Editor */}
            <textarea
              value={promptContent}
              onChange={(e) => setPromptContent(e.target.value)}
              rows={12}
              className="w-full bg-panel border border-border rounded-lg px-3 py-2.5 text-sm text-gray-300 font-mono focus:outline-none focus:border-indigo-500 resize-y"
            />

            <div className="flex items-center gap-4">
              <button
                onClick={handlePromptSave}
                disabled={promptMutation.isPending}
                className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
              >
                {promptMutation.isPending ? "Saving..." : "Save Prompt"}
              </button>
              {promptSaved && <span className="text-sm text-emerald-400">Prompt saved.</span>}
              {promptMutation.isError && <span className="text-sm text-red-400">Failed to save prompt.</span>}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
