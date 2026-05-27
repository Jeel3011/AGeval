"use client";

import React, { useState } from "react";
import { Users, Mail, UserPlus, MoreVertical, X, CheckCircle2, Loader2 } from "lucide-react";

export default function TeamPage() {
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);
  const [isInviting, setIsInviting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [teamMembers, setTeamMembers] = useState([
    { id: 1, name: "Alice Smith", email: "alice@acmecorp.com", role: "Owner", status: "Active" },
    { id: 2, name: "Bob Jones", email: "bob@acmecorp.com", role: "Admin", status: "Active" }
  ]);

  const handleInvite = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail) return;
    setIsInviting(true);
    setTimeout(() => {
      setIsInviting(false);
      setIsInviteModalOpen(false);
      setIsSuccess(true);
      setTeamMembers([...teamMembers, {
        id: Date.now(),
        name: "Pending...",
        email: inviteEmail,
        role: "Viewer",
        status: "Invited"
      }]);
      setInviteEmail("");
      setTimeout(() => setIsSuccess(false), 3000);
    }, 1500);
  };

  return (
    <div className="p-8 relative">
      
      {/* Toast Notification */}
      {isSuccess && (
        <div className="fixed bottom-6 right-6 bg-zinc-900 text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-in slide-in-from-bottom-5 fade-in duration-300 z-50">
          <CheckCircle2 size={18} className="text-emerald-400" />
          <span className="text-sm font-medium">Invitation sent successfully.</span>
        </div>
      )}

      {/* Invite Modal */}
      {isInviteModalOpen && (
        <div className="fixed inset-0 bg-zinc-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="bg-white rounded-xl shadow-xl border border-zinc-200 w-full max-w-md overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between bg-zinc-50/50">
              <h2 className="font-semibold text-zinc-900">Invite Team Member</h2>
              <button onClick={() => setIsInviteModalOpen(false)} className="text-zinc-400 hover:text-zinc-600 transition-colors">
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleInvite} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Email Address</label>
                <input 
                  type="email" 
                  autoFocus
                  required
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com" 
                  className="w-full h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Role</label>
                <select className="w-full h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400">
                  <option value="admin">Admin</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>
              <div className="pt-2 flex justify-end gap-3">
                <button type="button" onClick={() => setIsInviteModalOpen(false)} className="h-9 px-4 rounded-md text-sm font-medium text-zinc-600 hover:bg-zinc-100 transition-colors">
                  Cancel
                </button>
                <button type="submit" disabled={isInviting} className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors disabled:opacity-50">
                  {isInviting ? <Loader2 size={16} className="animate-spin" /> : <Mail size={16} />}
                  Send Invite
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="max-w-5xl mx-auto space-y-8">
        
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Team Management</h1>
            <p className="text-zinc-500 mt-1 text-sm">Manage members, roles, and access controls for this project.</p>
          </div>
          <button onClick={() => setIsInviteModalOpen(true)} className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors shadow-sm">
            <UserPlus size={16} />
            Invite Member
          </button>
        </div>

        <div className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden flex flex-col">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/80 border-b border-zinc-200">
                <tr>
                  <th className="px-6 py-3 font-medium">User</th>
                  <th className="px-6 py-3 font-medium">Role</th>
                  <th className="px-6 py-3 font-medium">Status</th>
                  <th className="px-6 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {teamMembers.map((member) => (
                  <tr key={member.id} className="bg-white hover:bg-zinc-50 transition-colors group">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-700 font-semibold text-xs">
                          {member.name === "Pending..." ? "?" : member.name.charAt(0)}
                        </div>
                        <div>
                          <div className="font-medium text-zinc-900">{member.name}</div>
                          <div className="text-zinc-500 text-xs">{member.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-zinc-600">
                      {member.role}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${member.status === 'Active' ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'}`}>
                        {member.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button className="text-zinc-400 hover:text-zinc-900 transition-colors">
                        <MoreVertical size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
