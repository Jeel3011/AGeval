"use client";

import React, { useState, useEffect } from "react";
import { Database, Plus, Search, UploadCloud, MoreVertical, Loader2, X } from "lucide-react";
import { datasetsApi, Dataset } from "@/lib/api-client";

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [newDatasetName, setNewDatasetName] = useState("");

  const fetchDatasets = () => {
    setIsLoading(true);
    datasetsApi.getDatasets("prj_9x8c7v6b")
      .then(data => {
        setDatasets(data);
        setIsLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch datasets:", err);
        setIsLoading(false);
      });
  };

  useEffect(() => {
    fetchDatasets();
  }, []);

  const handleCreateDataset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDatasetName.trim()) return;
    
    setIsSubmitting(true);
    try {
      await datasetsApi.createDataset({
        project_id: "prj_9x8c7v6b",
        name: newDatasetName,
        version: "v1",
        test_cases: [
          { input_data: { query: "test" }, expected_output: "test output" }
        ]
      });
      setIsModalOpen(false);
      setNewDatasetName("");
      fetchDatasets(); // Refresh table
    } catch (err) {
      console.error(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-8 relative">
      {/* Modal Overlay */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-zinc-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="bg-white rounded-xl shadow-xl border border-zinc-200 w-full max-w-md overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between bg-zinc-50/50">
              <h2 className="font-semibold text-zinc-900">Create New Dataset</h2>
              <button onClick={() => setIsModalOpen(false)} className="text-zinc-400 hover:text-zinc-600 transition-colors">
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleCreateDataset} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Dataset Name</label>
                <input 
                  type="text" 
                  autoFocus
                  required
                  value={newDatasetName}
                  onChange={(e) => setNewDatasetName(e.target.value)}
                  placeholder="e.g. Sales Inquiries v2" 
                  className="w-full h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                />
              </div>
              <div className="pt-2 flex justify-end gap-3">
                <button type="button" onClick={() => setIsModalOpen(false)} className="h-9 px-4 rounded-md text-sm font-medium text-zinc-600 hover:bg-zinc-100 transition-colors">
                  Cancel
                </button>
                <button type="submit" disabled={isSubmitting} className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors disabled:opacity-50">
                  {isSubmitting ? <Loader2 size={16} className="animate-spin" /> : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="max-w-6xl mx-auto space-y-8">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Golden Datasets</h1>
            <p className="text-zinc-500 mt-1 text-sm">Manage ground-truth datasets for evaluating your agents.</p>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 h-9 px-4 rounded-md border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 transition-colors shadow-sm">
              <UploadCloud size={16} />
              Import CSV/JSON
            </button>
            <button onClick={() => setIsModalOpen(true)} className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors shadow-sm">
              <Plus size={16} />
              New Dataset
            </button>
          </div>
        </div>

        <div className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden flex flex-col">
          <div className="h-14 border-b border-zinc-200 px-4 flex items-center justify-between bg-zinc-50/50">
            <div className="relative">
              <Search className="absolute left-2.5 top-2 h-4 w-4 text-zinc-400" />
              <input 
                type="text" 
                placeholder="Search datasets..." 
                className="h-8 w-72 rounded-md border border-zinc-200 bg-white pl-9 pr-4 text-sm outline-none focus:border-zinc-300 focus:ring-1 focus:ring-zinc-300 transition-all"
              />
            </div>
          </div>

          <div className="overflow-x-auto min-h-[300px]">
            {isLoading ? (
              <div className="flex flex-col items-center justify-center h-64 text-zinc-400">
                <Loader2 className="animate-spin mb-2" size={24} />
                <p className="text-sm">Fetching live datasets from backend...</p>
              </div>
            ) : (
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/80 border-b border-zinc-200">
                  <tr>
                    <th className="px-6 py-3 font-medium">Name</th>
                    <th className="px-6 py-3 font-medium">Test Cases</th>
                    <th className="px-6 py-3 font-medium">Version</th>
                    <th className="px-6 py-3 font-medium">Last Updated</th>
                    <th className="px-6 py-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {datasets.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="text-center py-8 text-zinc-500">No datasets found.</td>
                    </tr>
                  ) : (
                    datasets.map((ds) => (
                      <DatasetRow 
                        key={ds.id}
                        name={ds.name} 
                        count={ds.test_case_count} 
                        version={ds.version} 
                        time={ds.last_updated} 
                      />
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function DatasetRow({ name, count, version, time }: { name: string, count: number, version: string, time: string }) {
  return (
    <tr className="bg-white hover:bg-zinc-50 transition-colors group">
      <td className="px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center">
            <Database size={14} className="text-indigo-600" />
          </div>
          <span className="font-medium text-zinc-900">{name}</span>
        </div>
      </td>
      <td className="px-6 py-4 text-zinc-600">
        {count.toLocaleString()} cases
      </td>
      <td className="px-6 py-4">
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-zinc-100 text-zinc-600 border border-zinc-200">
          {version}
        </span>
      </td>
      <td className="px-6 py-4 text-zinc-500 whitespace-nowrap">
        {time}
      </td>
      <td className="px-6 py-4 text-right">
        <button className="text-zinc-400 hover:text-zinc-900 transition-colors">
          <MoreVertical size={16} />
        </button>
      </td>
    </tr>
  );
}
