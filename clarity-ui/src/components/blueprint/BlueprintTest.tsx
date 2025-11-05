/**
 * BlueprintTest - Test component for blueprint approval workflow
 * Provides mock data and trigger button to test the BlueprintModal
 */

import { Box, Button, Typography, Paper, Alert } from '@mui/material';
import { useBlueprintStore } from '../../stores/blueprintStore';
import BlueprintModal from './BlueprintModal';
import type { Blueprint } from '../../types/blueprint';

// Mock Blueprint Data
const mockBlueprint: Blueprint = {
  task_description: 'Implement user authentication system with JWT tokens',
  estimated_complexity: 'Medium',
  estimated_time: '4-6 hours',

  components: [
    {
      name: 'AuthService',
      type: 'service',
      purpose: 'Handle authentication logic and JWT token management',
      responsibilities: [
        'Validate user credentials',
        'Generate JWT access and refresh tokens',
        'Verify and refresh tokens',
        'Handle logout and token revocation'
      ],
      file_path: 'src/services/auth/AuthService.ts',
      layer: 'Service Layer',
      key_methods: ['login', 'logout', 'refreshToken', 'verifyToken'],
      dependencies: ['UserRepository', 'TokenManager', 'PasswordHasher']
    },
    {
      name: 'AuthController',
      type: 'api',
      purpose: 'REST API endpoints for authentication operations',
      responsibilities: [
        'Handle login requests',
        'Handle logout requests',
        'Handle token refresh requests',
        'Return appropriate HTTP responses'
      ],
      file_path: 'src/api/controllers/AuthController.ts',
      layer: 'API Layer',
      key_methods: ['POST /auth/login', 'POST /auth/logout', 'POST /auth/refresh'],
      dependencies: ['AuthService', 'ValidationMiddleware']
    },
    {
      name: 'TokenManager',
      type: 'util',
      purpose: 'Utility for JWT token generation and validation',
      responsibilities: [
        'Generate JWT tokens with proper claims',
        'Validate token signatures',
        'Check token expiration',
        'Extract user information from tokens'
      ],
      file_path: 'src/utils/TokenManager.ts',
      layer: 'Utility Layer',
      key_methods: ['generateAccessToken', 'generateRefreshToken', 'verifyToken', 'decodeToken'],
      dependencies: ['jsonwebtoken']
    },
    {
      name: 'UserRepository',
      type: 'database',
      purpose: 'Database access layer for user operations',
      responsibilities: [
        'Query user by username/email',
        'Store user session information',
        'Update last login timestamp',
        'Handle user account status'
      ],
      file_path: 'src/database/repositories/UserRepository.ts',
      layer: 'Data Layer',
      key_methods: ['findByUsername', 'findByEmail', 'updateLastLogin', 'saveRefreshToken'],
      dependencies: ['DatabaseConnection', 'User model']
    },
    {
      name: 'AuthMiddleware',
      type: 'function',
      purpose: 'Express middleware to protect routes requiring authentication',
      responsibilities: [
        'Extract JWT from request headers',
        'Verify token validity',
        'Attach user information to request',
        'Return 401 for invalid/missing tokens'
      ],
      file_path: 'src/middleware/AuthMiddleware.ts',
      layer: 'Middleware Layer',
      key_methods: ['authenticate', 'requireRole'],
      dependencies: ['TokenManager']
    }
  ],

  design_decisions: [
    {
      decision: 'Use JWT (JSON Web Tokens) for stateless authentication',
      rationale: 'JWT allows stateless authentication, reducing database queries for every authenticated request. Tokens contain user information and can be validated without server-side session storage.',
      alternatives_considered: [
        'Session-based authentication with server-side storage',
        'OAuth 2.0 with third-party providers',
        'API keys for service-to-service authentication'
      ],
      trade_offs: 'JWT tokens cannot be invalidated before expiration without additional infrastructure. Requires careful handling of token refresh and secure storage on client side.',
      category: 'Authentication Strategy'
    },
    {
      decision: 'Implement refresh token rotation',
      rationale: 'Using short-lived access tokens (15 minutes) with longer-lived refresh tokens (7 days) provides better security. Refresh token rotation prevents token reuse attacks.',
      alternatives_considered: [
        'Long-lived access tokens only',
        'Sliding session expiration',
        'Single refresh token without rotation'
      ],
      trade_offs: 'Adds complexity to token management and requires careful handling of token refresh logic. Client must implement token refresh before expiration.',
      category: 'Security'
    },
    {
      decision: 'Use bcrypt for password hashing with salt rounds = 12',
      rationale: 'bcrypt is specifically designed for password hashing with built-in salt generation. Salt rounds of 12 provides strong security while maintaining reasonable performance (200-300ms per hash).',
      alternatives_considered: [
        'argon2 (newer algorithm, higher memory requirements)',
        'PBKDF2 (older, still secure but slower)',
        'scrypt (high memory and CPU requirements)'
      ],
      trade_offs: 'Password hashing adds 200-300ms latency to login requests. Cannot be parallelized due to sequential nature of bcrypt.',
      category: 'Password Security'
    }
  ],

  file_actions: [
    {
      file_path: 'src/services/auth/AuthService.ts',
      action: 'create',
      description: 'Create authentication service with login/logout/refresh methods',
      estimated_lines: 150,
      components_affected: ['AuthService']
    },
    {
      file_path: 'src/api/controllers/AuthController.ts',
      action: 'create',
      description: 'Create REST API controller for authentication endpoints',
      estimated_lines: 120,
      components_affected: ['AuthController']
    },
    {
      file_path: 'src/utils/TokenManager.ts',
      action: 'create',
      description: 'Create JWT token manager utility',
      estimated_lines: 100,
      components_affected: ['TokenManager']
    },
    {
      file_path: 'src/database/repositories/UserRepository.ts',
      action: 'modify',
      description: 'Add methods for token storage and last login tracking',
      estimated_lines: 50,
      components_affected: ['UserRepository']
    },
    {
      file_path: 'src/middleware/AuthMiddleware.ts',
      action: 'create',
      description: 'Create authentication middleware for route protection',
      estimated_lines: 80,
      components_affected: ['AuthMiddleware']
    }
  ],

  relationships: [
    {
      source: 'AuthController',
      target: 'AuthService',
      type: 'calls',
      description: 'AuthController calls AuthService methods for business logic'
    },
    {
      source: 'AuthService',
      target: 'TokenManager',
      type: 'uses',
      description: 'AuthService uses TokenManager to generate and verify tokens'
    },
    {
      source: 'AuthService',
      target: 'UserRepository',
      type: 'uses',
      description: 'AuthService queries user data from UserRepository'
    },
    {
      source: 'AuthMiddleware',
      target: 'TokenManager',
      type: 'uses',
      description: 'AuthMiddleware uses TokenManager to verify request tokens'
    },
    {
      source: 'TokenManager',
      target: 'jsonwebtoken',
      type: 'imports',
      description: 'TokenManager imports JWT library for token operations'
    }
  ],

  prerequisites: [
    'User model and database schema must exist',
    'Express.js server must be configured',
    'jsonwebtoken and bcrypt packages must be installed',
    'Environment variables for JWT secrets must be configured'
  ],

  risks: [
    'Token secret leakage could compromise all user sessions',
    'Insufficient rate limiting could enable brute force attacks',
    'Token refresh timing issues could cause user session interruptions',
    'XSS vulnerabilities could lead to token theft from client storage'
  ]
};

export default function BlueprintTest() {
  const { openBlueprint, approvalDecision, reset } = useBlueprintStore();

  const handleOpenBlueprint = () => {
    reset();
    openBlueprint(mockBlueprint);
  };

  return (
    <Box sx={{ p: 4 }}>
      <Paper sx={{ p: 3, maxWidth: 800, mx: 'auto' }}>
        <Typography variant="h4" gutterBottom>
          Blueprint Approval Test
        </Typography>

        <Typography variant="body1" color="text.secondary" paragraph>
          This test page demonstrates the blueprint approval workflow. Click the button below
          to open the blueprint modal with mock data for a user authentication system.
        </Typography>

        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
            Test Features:
          </Typography>
          <Typography variant="body2" component="div">
            • 3-panel layout (Component Tree | Details | Design Decisions)
            <br />
            • Component selection and navigation
            <br />
            • Design decision expandable accordions
            <br />
            • Prerequisites and risks display
            <br />
            • Approve/Reject workflow with feedback form
          </Typography>
        </Box>

        <Button
          variant="contained"
          size="large"
          onClick={handleOpenBlueprint}
          sx={{ mb: 3 }}
        >
          Open Mock Blueprint
        </Button>

        {approvalDecision && (
          <Alert
            severity={approvalDecision.approved ? 'success' : 'error'}
            onClose={reset}
            sx={{ mb: 2 }}
          >
            <Typography variant="subtitle2" fontWeight="bold">
              {approvalDecision.approved ? 'Blueprint Approved!' : 'Blueprint Rejected'}
            </Typography>
            {!approvalDecision.approved && approvalDecision.feedback && (
              <Typography variant="body2" sx={{ mt: 1 }}>
                Feedback: {approvalDecision.feedback}
              </Typography>
            )}
            <Typography variant="caption" display="block" sx={{ mt: 1 }}>
              Timestamp: {approvalDecision.timestamp.toLocaleString()}
            </Typography>
          </Alert>
        )}

        <Typography variant="caption" color="text.secondary" display="block">
          Mock blueprint contains: 5 components, 3 design decisions, 5 file actions,
          5 relationships, 4 prerequisites, and 4 risks
        </Typography>
      </Paper>

      {/* The Modal */}
      <BlueprintModal />
    </Box>
  );
}
