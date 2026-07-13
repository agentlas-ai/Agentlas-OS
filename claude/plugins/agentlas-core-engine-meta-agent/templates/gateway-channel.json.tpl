{
  "schemaVersion": "agentlas.gateway-channel.v1",
  "gatewayId": "{{GATEWAY_ID}}",
  "ownerWorkspaceId": "{{WORKSPACE_ID}}",
  "setup": {
    "operatorGoal": "Connect this agent to a chat channel and prove delivery with one test message.",
    "recommendedFlow": "guided_token",
    "steps": [
      "choose_agent",
      "choose_channel",
      "authorize_provider",
      "save_credential_ref",
      "choose_conversation",
      "approve_pairing",
      "send_test_message",
      "confirm_receipt"
    ],
    "successChecks": [
      "Credential reference saved without exposing the token.",
      "A channel/account/peer binding resolves to the target agent.",
      "A test message returns a delivery receipt from the provider."
    ],
    "troubleshooting": [
      {
        "code": "credential_missing",
        "operatorMessage": "Save the provider token in the local secret store named by this contract, then retry the health check."
      },
      {
        "code": "pairing_required",
        "operatorMessage": "Send the pairing code from the Telegram account or chat you want to approve."
      },
      {
        "code": "receipt_missing",
        "operatorMessage": "The agent produced a reply, but the provider did not confirm delivery. Retry the test send before marking setup complete."
      }
    ]
  },
  "channels": {
    "{{CHANNEL_ID}}": {
      "provider": "{{CHANNEL_PROVIDER}}",
      "enabled": false,
      "mode": "long_polling",
      "capabilities": {
        "text": true,
        "images": false,
        "files": false,
        "voice": false,
        "threads": false,
        "typing": true,
        "streamingEdits": false,
        "backgroundDelivery": true
      },
      "setup": {
        "operatorGoal": "Connect {{CHANNEL_PROVIDER}} to {{AGENT_ID}}.",
        "recommendedFlow": "guided_token",
        "steps": [
          "choose_channel",
          "authorize_provider",
          "save_credential_ref",
          "choose_conversation",
          "approve_pairing",
          "send_test_message",
          "confirm_receipt"
        ]
      },
      "accounts": {
        "default": {
          "enabled": false,
          "displayName": "{{CHANNEL_DISPLAY_NAME}}",
          "credentials": {
            "botToken": {
              "source": "env",
              "id": "{{CHANNEL_BOT_TOKEN_ENV}}",
              "label": "Bot token environment variable"
            }
          },
          "access": {
            "dmPolicy": "pairing",
            "allowFrom": [],
            "groupPolicy": "allowlist",
            "groupAllowFrom": []
          },
          "commands": {
            "adminFrom": [],
            "userAllowedCommands": ["help", "whoami"],
            "dangerousActionApproval": "required"
          },
          "messageLimits": {
            "maxTextChars": 12000,
            "chunking": "adapter",
            "format": "platform_native"
          }
        }
      }
    }
  },
  "bindings": [
    {
      "agentId": "{{AGENT_ID}}",
      "sessionKey": "{{SESSION_KEY}}",
      "match": {
        "channel": "{{CHANNEL_ID}}",
        "accountId": "default",
        "peer": {
          "kind": "direct",
          "id": "{{PEER_ID_REF}}"
        }
      }
    }
  ],
  "delivery": {
    "toolProgress": "new",
    "progressGrouping": "accumulate",
    "backgroundNotifications": "result",
    "silenceTokens": ["SILENT", "NO_REPLY"]
  },
  "security": {
    "defaultDenyUnknownSenders": true,
    "pairingCodeTtlSeconds": 3600,
    "pairingRateLimitSeconds": 600,
    "redactIdentifiersInLogs": true,
    "storeRawMessageBodies": false
  }
}
