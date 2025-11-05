/**
 * Blueprint Store using Zustand
 * Manages blueprint approval workflow state
 */

import { create } from 'zustand';
import type { Blueprint, Component, ApprovalDecision } from '../types/blueprint';

interface BlueprintState {
  // State
  currentBlueprint: Blueprint | null;
  selectedComponent: Component | null;
  isModalOpen: boolean;
  approvalDecision: ApprovalDecision | null;
  
  // Actions
  openBlueprint: (blueprint: Blueprint) => void;
  closeBlueprint: () => void;
  selectComponent: (component: Component | null) => void;
  approve: () => void;
  reject: (feedback: string) => void;
  reset: () => void;
}

export const useBlueprintStore = create<BlueprintState>((set) => ({
  // Initial state
  currentBlueprint: null,
  selectedComponent: null,
  isModalOpen: false,
  approvalDecision: null,

  // Actions
  openBlueprint: (blueprint) => {
    set({
      currentBlueprint: blueprint,
      isModalOpen: true,
      selectedComponent: blueprint.components[0] || null,
      approvalDecision: null,
    });
  },

  closeBlueprint: () => {
    set({
      isModalOpen: false,
      selectedComponent: null,
    });
  },

  selectComponent: (component) => {
    set({ selectedComponent: component });
  },

  approve: () => {
    set({
      approvalDecision: {
        approved: true,
        timestamp: new Date(),
      },
      isModalOpen: false,
    });
  },

  reject: (feedback) => {
    set({
      approvalDecision: {
        approved: false,
        feedback,
        timestamp: new Date(),
      },
      isModalOpen: false,
    });
  },

  reset: () => {
    set({
      currentBlueprint: null,
      selectedComponent: null,
      isModalOpen: false,
      approvalDecision: null,
    });
  },
}));
