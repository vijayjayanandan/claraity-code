/**
 * Skill picker popover — shows available skills grouped by category
 * with checkboxes for selection (max 2 active).
 */
import { useState, useRef, useEffect, useCallback } from "react";
import type { SkillInfo } from "../types";

interface SkillPickerProps {
  skills: SkillInfo[];
  activeSkills: string[];
  onToggle: (skillId: string) => void;
  onRequestRefresh: () => void;
  onCreateSkill: () => void;
  onClose: () => void;
}

export function SkillPicker({
  skills,
  activeSkills,
  onToggle,
  onRequestRefresh,
  onCreateSkill,
  onClose,
}: SkillPickerProps) {
  const [filter, setFilter] = useState("");
  const pickerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Focus search on open
  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  // Request skills list on first open if empty
  useEffect(() => {
    if (skills.length === 0) {
      onRequestRefresh();
    }
  }, []);

  // Click-outside to close
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  // Filter skills
  const lowerFilter = filter.toLowerCase();
  const filtered = filter
    ? skills.filter(
        (s) =>
          s.name.toLowerCase().includes(lowerFilter) ||
          s.description.toLowerCase().includes(lowerFilter) ||
          s.tags.some((t) => t.toLowerCase().includes(lowerFilter)),
      )
    : skills;

  // Group by category
  const grouped: Record<string, SkillInfo[]> = {};
  for (const skill of filtered) {
    const cat = skill.category || "general";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(skill);
  }
  const categories = Object.keys(grouped).sort();

  const atLimit = activeSkills.length >= 2;

  const handleToggle = useCallback(
    (skillId: string) => {
      onToggle(skillId);
    },
    [onToggle],
  );

  return (
    <div className="skill-picker" ref={pickerRef}>
      <div className="skill-search">
        <input
          ref={searchRef}
          type="text"
          placeholder="Search skills..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
          }}
        />
      </div>

      <div className="skill-list">
        {categories.length === 0 && (
          <div className="skill-empty">
            {skills.length === 0 ? "No skills found. Create one to get started." : "No matching skills."}
          </div>
        )}

        {categories.map((cat) => (
          <div key={cat}>
            {categories.length > 1 && <div className="skill-category-header">{cat}</div>}
            {grouped[cat].map((skill) => {
              const isActive = activeSkills.includes(skill.id);
              const isDisabled = !isActive && atLimit;
              return (
                <div
                  key={skill.id}
                  className={`skill-item${isActive ? " active" : ""}${isDisabled ? " disabled" : ""}`}
                  onClick={() => !isDisabled && handleToggle(skill.id)}
                  title={isDisabled ? "Max 2 skills at once" : skill.description}
                >
                  <input
                    type="checkbox"
                    className="skill-checkbox"
                    checked={isActive}
                    disabled={isDisabled}
                    onChange={() => {}}
                    tabIndex={-1}
                  />
                  <div className="skill-item-text">
                    <div className="skill-name">{skill.name}</div>
                    <div className="skill-desc">{skill.description}</div>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="skill-picker-footer">
        <button onClick={onCreateSkill}>
          <i className="codicon codicon-add" /> New Skill
        </button>
      </div>
    </div>
  );
}
