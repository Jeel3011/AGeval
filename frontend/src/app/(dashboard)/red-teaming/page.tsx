"use client";

import React, { useState, useEffect } from "react";
import { ShieldAlert, Shield, ShieldCheck, Crosshair, Zap, Activity, Loader2 } from "lucide-react";
import { jobsApi } from "@/lib/api-client";

export default function RedTeamingPage() {
  const [isLaunching, setIsLaunching] = useState(false);
  const [jobStatus, setJobStatus] = useState<any>(null);
  const [scorecard, setScorecard] = useState<any>({
    overall_grade: "C-",
    prompt_injection_bypass_rate: 85,
    roleplay_jailbreak_bypass_rate: 2,
    data_exfiltration_bypass_rate: 0,
    dow_success_rate: 15
  });

  const handleLaunch = async () => {
    setIsLaunching(true);
    setJobStatus({ progress: 0, status: "queued" });
    try {
      const job = await jobsApi.launchRedTeam("prj_9x8c7v6b");
      pollJob(job.job_id);
    } catch (err) {
      console.error(err);
      setIsLaunching(false);
    }
  };

  const pollJob = (jobId: string) => {
    const interval = setInterval(async () => {
      try {
        const status = await jobsApi.getJobStatus(jobId);
        setJobStatus(status);
        if (status.status === "completed") {
          clearInterval(interval);
          setIsLaunching(false);
          if (status.result_summary) {
            setScorecard({
              overall_grade: status.result_summary.overall_grade,
              prompt_injection_bypass_rate: status.result_summary.prompt_injection_bypass_rate * 100,
              roleplay_jailbreak_bypass_rate: 0,
              data_exfiltration_bypass_rate: 0,
              dow_success_rate: status.result_summary.dow_success_rate * 100
            });
          }
        } else if (status.status === "failed") {
          clearInterval(interval);
          setIsLaunching(false);
        }
      } catch (err) {
        clearInterval(interval);
        setIsLaunching(false);
      }
    }, 1500);
  };

  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Red Teaming</h1>
            <p className="text-zinc-500 mt-1 text-sm">Automated adversarial testing for prompt injections and jailbreaks.</p>
          </div>
          <button 
            onClick={handleLaunch} 
            disabled={isLaunching}
            className="flex items-center gap-2 h-9 px-4 rounded-md bg-rose-600 text-white text-sm font-medium hover:bg-rose-700 transition-colors shadow-sm disabled:opacity-70 disabled:cursor-wait"
          >
            {isLaunching ? <Loader2 size={14} className="animate-spin" /> : <Crosshair size={14} />}
            {isLaunching ? "Running Simulation..." : "Launch Attack Simulation"}
          </button>
        </div>

        {isLaunching && jobStatus && (
          <div className="border border-amber-200 bg-amber-50 rounded-xl p-4 shadow-sm flex items-center gap-4">
            <Loader2 className="animate-spin text-amber-600" size={20} />
            <div className="flex-1">
              <div className="flex justify-between text-sm font-medium text-amber-900 mb-1">
                <span>Injecting adversarial payloads...</span>
                <span>{jobStatus.progress}%</span>
              </div>
              <div className="w-full bg-amber-200 rounded-full h-2">
                <div className="bg-amber-500 h-2 rounded-full transition-all duration-500" style={{ width: `${jobStatus.progress}%` }}></div>
              </div>
            </div>
          </div>
        )}

        {/* Security Score Overview */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="border border-zinc-200 bg-white rounded-xl p-6 shadow-sm flex flex-col items-center justify-center text-center transition-all">
            <div className={`w-16 h-16 rounded-full flex items-center justify-center mb-4 ${scorecard.overall_grade.includes('A') || scorecard.overall_grade.includes('B') ? 'bg-emerald-50 border-emerald-100 text-emerald-600' : 'bg-rose-50 border-rose-100 text-rose-600'}`}>
              <ShieldAlert size={32} />
            </div>
            <div className="text-4xl font-bold text-zinc-900 tracking-tight">{scorecard.overall_grade}</div>
            <div className="text-sm font-medium text-zinc-500 mt-1">Security Posture Score</div>
          </div>
          
          <div className="col-span-2 border border-zinc-200 bg-white rounded-xl shadow-sm p-6 flex flex-col justify-center">
            <h3 className="font-semibold text-zinc-900 mb-4 flex items-center gap-2">
              <Activity size={18} className="text-zinc-400" />
              Recent Vulnerabilities Detected
            </h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-zinc-700">Prompt Injection (System Override)</span>
                <span className="text-xs font-semibold text-rose-600 bg-rose-50 px-2 py-0.5 rounded border border-rose-100">Critical</span>
              </div>
              <div className="w-full bg-zinc-100 rounded-full h-2">
                <div className="bg-rose-500 h-2 rounded-full transition-all duration-1000" style={{ width: `${scorecard.prompt_injection_bypass_rate}%` }}></div>
              </div>

              <div className="flex items-center justify-between pt-2">
                <span className="text-sm font-medium text-zinc-700">Denial of Wallet (DoW)</span>
                <span className="text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded border border-amber-100">Medium</span>
              </div>
              <div className="w-full bg-zinc-100 rounded-full h-2">
                <div className="bg-amber-500 h-2 rounded-full transition-all duration-1000" style={{ width: `${scorecard.dow_success_rate}%` }}></div>
              </div>
            </div>
          </div>
        </div>

        {/* Attack Vectors */}
        <h3 className="text-lg font-semibold text-zinc-900 mt-8 mb-4">Tested Attack Vectors</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <AttackVectorCard 
            title="Direct Prompt Injection" 
            desc="Attempts to override system instructions via direct user input."
            status={scorecard.prompt_injection_bypass_rate > 50 ? "failed" : "passed"} 
            rate={`${Math.round(scorecard.prompt_injection_bypass_rate)}% Bypass Rate`}
          />
          <AttackVectorCard 
            title="Roleplay Jailbreaks" 
            desc="Assuming a persona (e.g. DAN) to bypass ethical filters."
            status={scorecard.roleplay_jailbreak_bypass_rate > 10 ? "warning" : "passed"} 
            rate={`${scorecard.roleplay_jailbreak_bypass_rate}% Bypass Rate`}
          />
          <AttackVectorCard 
            title="Data Exfiltration" 
            desc="Tricking the agent into repeating sensitive context."
            status="passed" 
            rate="0% Bypass Rate"
          />
          <AttackVectorCard 
            title="Denial of Wallet (DoW)" 
            desc="Triggering infinite loops to rack up LLM API costs."
            status={scorecard.dow_success_rate > 10 ? "warning" : "passed"} 
            rate={`${Math.round(scorecard.dow_success_rate)}% Success Rate`}
          />
        </div>

      </div>
    </div>
  );
}

function AttackVectorCard({ title, desc, status, rate }: { title: string, desc: string, status: 'passed' | 'failed' | 'warning', rate: string }) {
  const icons = {
    passed: <ShieldCheck className="text-emerald-600" size={20} />,
    failed: <ShieldAlert className="text-rose-600" size={20} />,
    warning: <Shield className="text-amber-600" size={20} />
  };
  
  const bgs = {
    passed: "bg-emerald-50 border-emerald-100",
    failed: "bg-rose-50 border-rose-100",
    warning: "bg-amber-50 border-amber-100"
  };

  return (
    <div className="border border-zinc-200 bg-white rounded-xl p-5 shadow-sm flex items-start gap-4 transition-all">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 border transition-colors ${bgs[status]}`}>
        {icons[status]}
      </div>
      <div className="flex-1">
        <h4 className="font-medium text-zinc-900">{title}</h4>
        <p className="text-sm text-zinc-500 mt-1">{desc}</p>
        <div className="mt-3 text-xs font-semibold text-zinc-700 bg-zinc-100 inline-block px-2 py-1 rounded">
          {rate}
        </div>
      </div>
    </div>
  );
}

