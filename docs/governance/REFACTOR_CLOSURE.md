> R01–R03 follow-up (12 September 2026) is recorded at the end of this report.
> Earlier results and limitations below are historical evidence for their named SHAs.
> This report was restored with explicit owner approval after documentation-only
> commit `c90e3ddcd167472e2838f7eba724c6cf88f3f63d`; other owner deletions remain intact.

# Correctness and architecture closure evidence

Owner assignment: `METOR_REFACTOR_CLOSURE_PROMPT_b8a172c.md`, 11 September 2026.
This is implementation evidence, not independent owner acceptance. The preceding
[remediation report](REFACTOR_2_FINAL_REMEDIATION.md) remains historical evidence
for its reviewed SHA; its broad PASS labels do not supersede this report.

## Provenance and boundaries

- Branch: `embeddedui`. Reviewed and actual starting HEAD:
  `b8a172c16013118e1526dece25fcaea40221e926`. Initial worktree clean, no newer
  commits to reconcile. No reset, history rewrite or owner changes overwritten.
- Ending SHA: supplied in the delivery handoff; the commit containing this report
  cannot embed its own hash. All source/tests/tools described here precede the
  final evidence commit. Final worktree verification is recorded in the handoff.
- Implementation commit: `694908af58bbe9a3e5788415ee9e0e7cf636b419`.
- Strengthened installed-Terminal probe: `594ff7694e5f561ec81bb4e3d6f0a967a5d5dfdd`.
- SDK/base/Terminal remain three disjoint namespace distributions, exactly pinned
  at `0.2.0`. No GUI distribution, daemon wheel, extras or meta-wheel added.
- No GUI/layout specification, `docs/.temp/EMBEDDED_UI_SPEC.md`, functional draft,
  toolkit, audio/device policy or screen implementation changed. Only the current
  Core/SDK integration references in `docs/contracts/EMBEDDED_UI.md` changed.
- All security/destruction tests use temporary profiles and test keys. No production
  peer contact, profile deletion, global insecure setting, release or remote push.

Evidence labels used below:

- **SC**: source-confirmed ownership/contract inspection.
- **LT**: local executable regression (including deliberate faults).
- **NI**: native-platform local execution, not a cross-platform typecheck.
- **CI**: hosted native GitHub Actions execution; unavailable for this unpushed work.
- **AI**: built-artifact isolated installation, never editable/source imports.
- **II**: controlled integration: real SDK, daemon dispatch, SQL receipts and encrypted
  blobs or real local sockets; only Tor/process/policy/failure collaborators controlled.
- **UV**: explicitly unverified; never counted as a passing test.

## Ownership and compatibility decisions

SDK owns deterministic auth/PIN proofs (`core/auth/session.py`, `pin.py`), shared
wire constants, onion helpers and mutable-buffer clearing. Base `utils` reexports
canonical functions where an existing facade is useful; duplicate implementations
are removed. Host paths, `.env`, filesystem deletion and process handling stay in
base; Terminal rendering constants stay in Terminal. Known-answer tests preserve
proof bytes/domain separation/KDF parameters. Explicit
`application.initialize_runtime_environment()` preserves the CLI/daemon `.env`
behavior after side-effect-free help/version gates; SDK imports never resolve HOME.

`core.auth` and `versioning` are narrowly promoted from single modules to packages
to own namespace type markers while retaining public import names. Markers belong
only to SDK-owned `client`, `core.api`, `core.auth`, `shared`, and `versioning`.
There is no namespace-root `metor/py.typed` claiming files from other wheels.

The existing frontend launch contract remains **v2**. Its endpoint is now non-null;
typed error reasons, retry and bounded client/UI settings writes complete that
contract. Matching official distribution pins prevent mixed old/new host contracts.
No IPC DTO, wire schema, SQL schema, keyslot/blob format or cryptographic derivation
generation changed. `fallback_committed` is optional internal receipt JSON recording
a repair intent; absent means false. It does not change message identity or delivery
semantics. Restored recordings do not regain runtime-scoped restricted authority.

Cohesion review (S02): StateTracker's implementation moved to `state/tracker.py`;
the facade only exports symbols. SQL mixins now share an explicitly typed
`message/receipts.py` collaborator, not `__getattr__ -> Any`. Focused collaborators
are `engine/capabilities.py` (exact pending grants), `engine/release.py` (release
outcomes), `client/outcomes.py` (event classifications), and
`application/frontend_settings.py` (bounded settings service). Session authorization,
Voice capture/transaction transitions and SDK generation ownership remain in their
existing subsystem state machines: the assignment explicitly rejects a wholesale
transport rewrite or arbitrary line-count splits. Their locks and rollback decisions
must remain auditable together. Existing small CLI/Terminal presentation adapters
remain separate because prompts, ANSI and grammar are frontend responsibilities,
not shared security policy. No new generic helpers/common/presentation wheel.

Tokenizer logical-statement counts (NEWLINE tokens, including docstrings) after
review: session access474, Voice outbound573, Voice manager521, SDK IPC368,
SDK session172, host bootstrap134. Long physical line counts include expanded DTO
calls and documentation; the touched implementations are below the canonical
800-logical-line guardrail. The reviewed >500 Voice modules retain their existing
capture/transaction boundaries rather than splitting one commit/rollback protocol
across new unrelated files.

Lock order: command/domain barrier → release serialization for stop/lock; domain
barrier → state/receipt/Voice transition locks for snapshots and mutation. Writers
claim generation authority under the transition lock, then perform socket I/O outside
it. An already claimed frame can be in flight; revocation prevents new claims, not an
impossible recall. Final frames use bounded writer-owned drain/close, not sleeps or
blocking peer ACKs under canonical locks. Purge cancels ordinary reliability work.

## Functional and structural trace

All production paths in this section are relative to `src/metor/`. Test abbreviations
are defined below. Platforms/results refer to the final verification ledger, not to
the reviewed baseline's failing Windows CI.

| Workstream | Implementation and reproduced cause | Exact enclosing regression evidence |
| --- | --- | --- |
| F01 | `core/daemon/managed/quick_unlock.py`: native `-Command` parameter binding left Target empty. Constant `-EncodedCommand` plus UTF-8 stdin fixes data/code separation. A second native replacement failure was `Set-Acl` requesting unavailable SeSecurityPrivilege; Directory/File.SetAccessControl applies owner/DACL without SACL. Protected current-user/SYSTEM FullControl, owner SID, symlink/reparse checks and 10s fail-closed helper bound remain. Writer failure fixture now explicitly shuts down the write side with the peer open. | I.`test_native_credential_configure_verify_replace_invalid_remove`; F.`test_windows_acl_helpers_are_bounded_and_fail_safely`; F.`test_writer_survives_idle_and_failure_closes_real_socket`; S.`test_quick_unlock_verifier_has_owner_only_permissions`, `test_windows_acl_validation_rejects_extra_trustee`. NI/II. |
| F02 | `engine/session_access.py`, `capabilities.py`, `network/voice/models.py`, `manager.py`, controller/state callbacks: event and command authority use frozen logical LIVE context plus exact turn/direction. Anonymous grants bind runtime/restriction/session, exact pending socket and deadline; bounded/deduplicated, policy denial does not consume. Atomic compare/pop prevents replacement inheritance. Sensitive auth implementation retained, not replaced with a global boolean. | I.`test_restricted_broadcast_uses_turn_provenance_not_current_peer`, `test_exact_anonymous_pending_replacement_and_duplicate_handle`; F.`test_restricted_media_is_direction_delivery_and_context_bound`, `test_live_context_generation_survives_recovery_not_new_conversation`; CS.`test_full_auth_restrict_pin_none_idempotence_purpose_expiry_and_replay`; S.`test_anonymized_call_handles_are_unique_actionable_and_expirable`. LT/II/NI. |
| F03 | `client/ipc.py`, `session.py`, `outcomes.py`, `auth.py`: explicit RequestLease captures generation/ID/socket through registration, send, auth follow-up, wait, leftovers and cleanup. Duplicate active IDs fail. Serialized publication and independent loss control survive full callback queues. Callback-generation resource bound prevents unlimited blocked-worker accumulation. Progress is delivered once, terminal result belongs to caller, incompatible correlated data raises protocol error. | I.`test_actual_finalize_fallback_progress_then_terminal_result`, `test_old_send_wait_cleanup_and_overflow_cannot_touch_replacement`, `test_full_callback_queue_has_unlosable_disconnect_control`; E.`test_public_exact_crossing_and_shared_limit_finalize_admitted_prefix`; D.`test_concurrent_first_requests_start_exactly_one_reader`, `test_disconnect_callback_reconnect_starts_fresh_generation_workers`. II/NI. |
| F04 | `writer.py`, `network/state/tracker.py`, `connections.py`, controller `session/terminate.py`, `manager.py`: carry failed socket identity to atomic removal; stale failures cannot mutate winning context/history/grace. Bounded FIFO final frame owns half-close and physical descriptor cleanup. Destructive cancellation stays distinct. | I.`test_stale_writer_failure_cannot_mutate_replacement_context`, `test_actual_manual_disconnect_orders_final_frame_without_blocking_ipc`, `test_final_frame_drains_before_eof_and_timeout_closes_descriptor`, `test_blocked_final_drain_deadline_retires_actual_writer_registry`; H.`test_blocked_writer_does_not_stall_actual_daemon_command_dispatch`; A.`test_bounded_writer_drops_invalidated_queued_generation`. II/NI. |
| F05 | `network/voice/outbound.py`, `manager.py`, `models.py`, router `fallback.py`, `data/sql/message/outbox.py`: remove empty-ID draft sweep. Canonical explicit committed fallback intent repairs partial promotion on same IDs, peer and direction. Invalid new mixed selection validates before mutation. False/raised writes deny terminal success. Commit-then-raise is reconciled against actual receipt before deleting bytes; unavailable canonical state retains possibly committed segments and retires speculative RAM. | I.`test_no_pending_fallback_does_not_take_unfinalized_drop_draft`, `test_explicit_partial_fallback_retry_same_process_and_restart`, `test_ambiguous_append_commit_reconciles_before_blob_rollback`, `test_inbound_commit_then_raise_reconciles_begin_chunk_and_end`; E.`test_false_and_exception_metadata_never_report_terminal_success`, `test_public_exact_crossing_and_shared_limit_finalize_admitted_prefix`; A.`test_interrupted_drop_draft_promotion_reconciles_before_review`. II/NI. |
| F06 | `engine/lifecycle.py`, `daemon.py`, `release.py`: independently attempt authority/workers/network/Tor/DB/plaintext mirror/blob keys/profile keys/handlers; failure remains LOCKING with structured failed phases and retryable stop. Disk keyslot destruction is not claimed as full live-key or physical erasure. Domain-before-release fixes concurrent stop/dispatch lock inversion. | I.`test_release_failure_attempts_all_resources_and_retries_stop`, `test_external_stop_waits_for_domain_before_claiming_release`; H.`test_self_destruct_dispatch_survives_abort_and_notification_failures`; F.`test_destruction_attempts_disk_key_after_every_preparation_failure`; P.`test_key_destruction_failure_prevents_cleanup_and_reports_phase`. LT/II/NI. |
| F07 | `application/frontend.py`, `frontend_settings.py`, `client/frontends.py`, Terminal launcher/session/chat: active dynamic port, typed failures, serialized retry/create/select, one-use secrets and start receipt prevent duplicate startup after post-start failure. Remote forwarded endpoint never starts local daemon. Terminal no longer reconstructs ProfileManager. | I.`test_dynamic_public_host_and_real_snapshot`, `test_actual_profile_switch_a_b_a_preserves_text_voice_off_and_on`; B.`test_public_missing_create_cancel_transient_start_and_retry`, `test_remote_forwarded_endpoint_never_launches_local_daemon`; AI installed fake launcher → base dispatcher → deferred host → real dynamic IPC, without Terminal or TTY. |
| S01 | Canonical SDK proof/constants/onion/memory-clear ownership and explicit base environment initialization described above. No copied implementations or host side effects in SDK import. | X.`test_security_primitives_have_one_owner_and_known_answers`, `test_sdk_import_is_inert_in_a_fresh_process`; AI SDK-only inert import/strict consumer. SC/LT/NI/AI. |
| S02 | Thin StateTracker facade; real RLock collaborators; shared typed SQL receipt store; bounded frontend settings and focused outcome/release/capability extractions. Official frontend metadata remains one inert base catalog, not entrypoint registration or copied UI schema. | X.`test_all_distribution_boundaries`; I dynamic-host settings namespace checks and concurrent snapshot/writer/stop tests; strict MyPy. SC/LT/II/NI. |
| S03 | Root `AGENTS.md` router, canonical AGENTS/CONTRIBUTE/ARCHITECTURE/GLOSSARY/README/RELEASING and Copilot/Cursor pointers reconciled; historical report clearly labeled. No GUI/layout spec edits. | Source/link inspection; generator freshness; this map. SC/LT. |
| S04 | `scripts/check_boundaries.py` structurally resolves aliased, multiline, relative and facade imports. Namespace-owned typing markers, clean documented developer setup and CI install all three distributions deliberately. `validate_installed_artifacts.py` exercises positive/negative external strict typing and uninstall ownership. | X.`test_negative_imports_include_facades_relative_aliases_and_multiline`, `test_all_distribution_boundaries`; version/wheel validator; fresh developer `pip check`/entrypoint discovery; AI matrix. |
| V01 | Retain shared snapshot barriers; prove real profile/storage/client integration, mutation before publication, retained inventory, epoch/revision and failure states. Native tests plus actual offline ZIP installers, freshness against originals, compatibility/source registration, installed typing and dependency closure. | I.`test_actual_snapshot_waits_for_store_mutation_before_publication`, `test_actual_profile_switch_a_b_a_preserves_text_voice_off_and_on`; A.`test_fresh_client_discovers_reads_and_releases_retained_voice`; final ledger below. Hosted CI remains UV until run on the delivered commits. |

## Test source key

Each `prefix.method` below means the exact `test_...` method in this linked file;
unittest's `-v` log records its class, method and result. Prefixes do not refer to
invented umbrella tests.

| Prefix | Source |
| --- | --- |
| I | [test_closure_integration.py](../../tests/test_closure_integration.py) |
| E | [test_closure_voice_edges.py](../../tests/test_closure_voice_edges.py) |
| X | [test_closure_architecture.py](../../tests/test_closure_architecture.py) |
| B | [test_closure_frontend.py](../../tests/test_closure_frontend.py) |
| CS | [test_closure_security.py](../../tests/test_closure_security.py) |
| A | [test_acceptance_repair_contract.py](../../tests/test_acceptance_repair_contract.py) |
| F | [test_final_remediation_contract.py](../../tests/test_final_remediation_contract.py) |
| S | [test_session_auth_contract.py](../../tests/test_session_auth_contract.py) |
| H | [test_daemon_hardening.py](../../tests/test_daemon_hardening.py) |
| P | [test_profile_storage_security.py](../../tests/test_profile_storage_security.py) |
| M | [test_message_architecture_contract.py](../../tests/test_message_architecture_contract.py) |
| D | [test_client_demux_contract.py](../../tests/test_client_demux_contract.py) |
| Q | [test_data_persistence_contract.py](../../tests/test_data_persistence_contract.py) |
| C | [test_chat_contract.py](../../tests/test_chat_contract.py) |
| V | [test_voice_contract.py](../../tests/test_voice_contract.py) |
| CLI | [test_refactor2_cli_contract.py](../../tests/test_refactor2_cli_contract.py) |

## Previous-backlog reconciliation

| Prior ID | Preserved repair and closing owner |
| --- | --- |
| C01 | POSIX availability-safe typing and bounded helper preserved; actual native ACL defects repaired F01; installed native proof S04/V01. |
| C02 | Idempotent auth and purpose-bound one-use grants preserved; actual full→restrict→PIN/NONE→bad idempotent proof regression F02. |
| C03 | Non-retiring bounded writer/physical-close separation preserved; deterministic failure F01, exact failure/final-frame integration F04. |
| C04 | Nonallocating replay preserved; writer claim linearization F04, canonical fallback repair F05. |
| C05 | Existing exception rollback preserved and ambiguous commit handling extended F05; actual SDK outcomes F03. |
| C06 | Standalone key-first coordinator preserved; actual independently attempted runtime release and retry F06. |
| C07 | One-reader/request fan-out preserved; end-to-end lease ownership, explicit progress, unlosable disconnect F03. |
| C08 | Shared snapshot barrier retained; actual stores/dispatch integration V01, explicit typed lock ownership S02. |
| C09 | Prior command gate preserved; passive Voice provenance and exact pending capabilities F02. |
| C10 | Phase-aware coordinator preserved; actual A→B→A local client/storage and locked-target failure V01/F07. |
| C11 | Deferred v2 host/one-use secret preserved; dynamic endpoint/retry/settings and Terminal boundary completed F07. |
| V01 | Earlier Linux-only/native-unverified claims replaced by current NI/AI ledger; remote CI explicitly separate. |
| STR-01 | Shared semantic constants have one SDK owner, S01. |
| STR-02 | Onion/proof implementation ownership consolidated, S01. |
| STR-03 | Mutable clearing separated from host deletion; SDK import inert, S01. |
| STR-04 | Presentation adapters remain independently owned; no indiscriminate deduplication, S02. |
| STR-05 | Bounded frontend host/settings, no storage facade substitute, F07/S02. |
| STR-06 | Thin facade/typed collaborators/cohesion review, S02. |
| STR-07 | Root routing and canonical guidance, S03. |
| STR-08 | Presentation versus operational state and recovery contracts reconciled, S03. |
| STR-09 | Bounded maintenance and base-only human TypeCaster guidance, S03. |
| STR-10 | Current versus historical evidence and truthful security wording, S03. |
| STR-11 | Executable structural boundaries with negative fixtures, S04. |
| STR-12 | Installed typing, disjoint markers, full developer registration and artifacts, S04/V01. |

## R2-T01–R2-T36 regression trace

LT tests below execute on both native hosts unless an explicit native skip is listed
in the ledger. AI rows refer to the named installed scripts, not repository imports.

| ID | Exact evidence |
| --- | --- |
| R2-T01 | `validate_installed_artifacts.py`: SDK_PROBE, GOOD_CONSUMER, BAD_CONSUMER; canonical proof use without base/SQLCipher. |
| R2-T02 | S.`test_quick_unlock_verifier_has_owner_only_permissions`, `test_quick_unlock_rejects_unsafe_parent_and_oversized_metadata`; I native credential lifecycle (POSIX branch). |
| R2-T03 | I.`test_native_credential_configure_verify_replace_invalid_remove` executes real Windows ACL create/replace/effective extra-trustee rejection/failed protection/invalid metadata/remove; F helper bound. |
| R2-T04 | S.`test_forgot_pin_issues_password_challenge_without_failed_attempt`, `test_restricted_client_enforces_scope_and_pin_password_escalation`. |
| R2-T05 | S.`test_restricted_client_enforces_scope_and_pin_password_escalation`, `test_restricted_password_retries_share_global_cooldown`; H.`test_daemon_reports_local_auth_rate_limit_during_locked_startup`. |
| R2-T06 | CS.`test_full_auth_restrict_pin_none_idempotence_purpose_expiry_and_replay`; S.`test_quick_unlock_configuration_requires_full_password_proof`. |
| R2-T07 | S.`test_device_lifecycle_scope_requires_prior_authenticated_session`; H.`test_locked_daemon_rejects_self_destruct_command`, `test_unauthenticated_self_destruct_requires_session_auth`. |
| R2-T08 | H.`test_self_destruct_dispatch_survives_abort_and_notification_failures`; F.`test_destruction_attempts_disk_key_after_every_preparation_failure`. |
| R2-T09 | P.`test_key_destruction_failure_prevents_cleanup_and_reports_phase`, `test_profile_destruction_is_idempotent_when_files_are_missing`; I.`test_release_failure_attempts_all_resources_and_retries_stop`. |
| R2-T10 | H.`test_blocked_writer_does_not_stall_actual_daemon_command_dispatch`; I.`test_actual_manual_disconnect_orders_final_frame_without_blocking_ipc`. |
| R2-T11 | A.`test_bounded_writer_drops_invalidated_queued_generation`, `test_common_replay_keeps_text_and_voice_frames_typed`; H.`test_router_replays_unacked_messages_over_recovered_live_socket`. |
| R2-T12 | A.`test_stale_live_ack_waits_behind_atomic_fallback_transition`, `test_purge_fence_wins_after_voice_finalize_passes_initial_guard`, `test_purge_stop_wins_after_outbox_ack_passes_initial_guard`. |
| R2-T13 | Q.`test_selective_fallback_is_atomic_and_preserves_message_identity`; I.`test_explicit_partial_fallback_retry_same_process_and_restart` invalid new ID branch. |
| R2-T14 | V.`test_live_voice_allows_simultaneous_inbound_and_outbound_turns`; A.`test_segment_storage_is_linear_and_socket_frames_do_not_interleave`, `test_slow_voice_peer_does_not_stall_another_peer`. |
| R2-T15 | E.`test_public_exact_crossing_and_shared_limit_finalize_admitted_prefix` (three explicit schedules, actual SDK/dispatch); A.`test_voice_byte_quota_rejects_growth_without_partial_storage`. |
| R2-T16 | E exact/crossing DROP cases assert no outbox eligibility; A.`test_drop_voice_draft_requires_commit_and_can_be_cancelled`; I.`test_no_pending_fallback_does_not_take_unfinalized_drop_draft`. |
| R2-T17 | E.`test_false_and_exception_metadata_never_report_terminal_success`; I.`test_inbound_commit_then_raise_reconciles_begin_chunk_and_end`, `test_ambiguous_append_commit_reconciles_before_blob_rollback`. |
| R2-T18 | A.`test_partial_live_promotes_to_drop_with_same_identity_and_full_bytes`, `test_duplicate_end_repeats_terminal_commit_ack`; V.`test_consumed_live_voice_duplicate_is_terminally_acknowledged`. |
| R2-T19 | A.`test_duplicate_chunk_is_idempotent_but_conflict_is_malformed`, `test_duplicate_end_repeats_terminal_commit_ack`, `test_stale_live_ack_waits_behind_atomic_fallback_transition`. |
| R2-T20 | A.`test_interrupted_encrypted_blob_promotion_reconciles_on_restart`, `test_interrupted_drop_draft_promotion_reconciles_before_review`; I explicit partial repair/restart and inbound/outbound ambiguous-write tests. |
| R2-T21 | A.`test_segment_storage_is_linear_and_socket_frames_do_not_interleave`, `test_public_bounded_read_precedes_explicit_release`. |
| R2-T22 | I.`test_actual_snapshot_waits_for_store_mutation_before_publication`; M.`test_runtime_snapshot_retries_when_state_mutates_before_publication`. |
| R2-T23 | D.`test_event_before_snapshot_response_is_not_discarded`; I.`test_full_callback_queue_has_unlosable_disconnect_control`; F.`test_snapshot_barrier_excludes_mutate_and_restore_windows`. |
| R2-T24 | M.`test_snapshot_state_distinguishes_recovery_and_terminal_disconnect`; H.`test_remote_fallback_disconnect_keeps_unacked_live_messages_during_grace`. |
| R2-T25 | A.`test_fresh_client_discovers_reads_and_releases_retained_voice`. |
| R2-T26 | Q.`test_retained_inventory_is_paginated_non_consuming_and_stale_safe`; F.`test_restricted_media_is_direction_delivery_and_context_bound`; I restricted broadcast provenance test. |
| R2-T27 | D.`test_concurrent_first_requests_start_exactly_one_reader`, `test_connection_loss_wakes_every_waiter_and_reconnect_resets_state`; I old-send/reused-ID/finally/overflow lease test. |
| R2-T28 | I.`test_actual_profile_switch_a_b_a_preserves_text_voice_off_and_on`: real SDK/dispatch/stores, controlled Tor, both fallback values and failed locked target. Real Tor latency is UV, not required local proof. |
| R2-T29 | A.`test_normal_exit_preserves_pending_text_and_voice_locally`, `test_purge_stop_wins_after_outbox_ack_passes_initial_guard`; I repeated release-failure test. |
| R2-T30 | CLI.`test_all_help_variants_are_profile_and_frontend_side_effect_free`, `test_version_is_profile_and_frontend_independent`; AI base-only help/daemon help. |
| R2-T31 | C.`test_chat_help_lists_slash_help_command`, `test_terminal_header_owns_chat_help_for_startup_and_redraw`; AI Terminal help/inventory. |
| R2-T32 | CLI.`test_selected_frontend_precedence_and_launch_context`, `test_non_chat_ui_tokens_remain_user_data`, `test_broken_selected_plugin_is_typed_and_does_not_load_siblings`, `test_discovery_rejects_duplicates_and_contract_mismatch`. |
| R2-T33 | `validate_wheel_versions.py` actual member ownership; `validate_installed_artifacts.py` UI/base uninstall/reinstall and SDK-survival sequences. |
| R2-T34 | `validate_release_installers.py` executes all three native ZIP installers; installed-artifact matrix on native Linux and Windows. |
| R2-T35 | Q.`test_delivery_filtered_consume_does_not_touch_other_projection`, `test_clear_messages_preserves_live_and_pending_drop_delivery`, `test_single_drop_delete_rejects_pending_delivery`, `test_saved_contact_with_history_and_ram_alias_is_only_downgraded`; existing chat/history suites. |
| R2-T36 | `validate_generated_docs.py` originals plus two generations; X.`test_deterministic_generation_does_not_hide_stale_checked_in_files`; `versioning.py validate`, compatibility validator. |

## Original Document-1 scenarios A–T

Source: unchanged `docs/.temp/CORE_TERMINAL_REFACTORING.md`, scenario headings.

| Scenario | Exact evidence |
| --- | --- |
| A selective Text fallback | Q.`test_selective_fallback_is_atomic_and_preserves_message_identity`. |
| B bulk fallback | H.`test_router_convert_unacked_messages_to_drop_uses_drop_type`; I no-pending draft isolation. |
| C disconnected LIVE, fallback OFF | H.`test_send_message_without_live_connection_stays_silent_during_reconnect_grace`; A.`test_profile_return_does_not_resurrect_live_reconnect_intent`. |
| D genuine reconnect | H.`test_router_replays_unacked_messages_over_recovered_live_socket`; C.`test_send_chat_message_uses_daemon_buffer_during_grace_reconnect`. |
| E overflow implicit hangup | H.`test_async_drop_stops_without_ack_when_drop_backlog_limit_is_reached`; V.`test_inbound_voice_obeys_headless_unseen_count_policy`. |
| F DROP-only clear | Q.`test_clear_messages_preserves_live_and_pending_drop_delivery`. |
| G delivery-aware mark-read | Q.`test_delivery_filtered_consume_does_not_touch_other_projection`; A.`test_text_consume_and_live_dismiss_preserve_other_voice_state`. |
| H remote read receipts disabled | E.`test_read_receipt_policy_controls_only_transient_peer_notification`: actual consume/receipt setting and FIFO socket barrier; delivery ACK versus read receipt remains distinct. |
| I single DROP delete | Q.`test_single_drop_delete_rejects_pending_delivery`; A.`test_direction_collision_deletes_only_selected_receipt`. |
| J dismiss disconnected LIVE | A.`test_text_consume_and_live_dismiss_preserve_other_voice_state`. |
| K snapshot race | I.`test_actual_snapshot_waits_for_store_mutation_before_publication`; M revision retry/exhaustion tests. |
| L Voice streaming/full duplex | V.`test_live_voice_allows_simultaneous_inbound_and_outbound_turns`; A serialization/slow-peer tests. |
| M Voice resume | A.`test_progress_ack_never_releases_before_terminal_commit`, `test_duplicate_chunk_is_idempotent_but_conflict_is_malformed`, `test_duplicate_end_repeats_terminal_commit_ack`. |
| N Voice fallback | A.`test_partial_live_promotes_to_drop_with_same_identity_and_full_bytes`; I explicit partial same-process/restart test. |
| O Voice pressure | E.`test_public_exact_crossing_and_shared_limit_finalize_admitted_prefix`; A explicit draft commit/cancel. |
| P restricted client | I restricted broadcast/context/exact pending tests; S lock-scope/PIN policy tests; CS actual auth sequence. |
| Q PIN escalation | S.`test_restricted_client_enforces_scope_and_pin_password_escalation`, `test_forgot_pin_issues_password_challenge_without_failed_attempt`. |
| R profile switch | I.`test_actual_profile_switch_a_b_a_preserves_text_voice_off_and_on`; F.`test_profile_switch_failure_keeps_candidate_unpublished`. |
| S normal power-off preparation | A.`test_normal_exit_preserves_pending_text_and_voice_locally`; I repeated cleanup-failure test. No actual host shutdown. |
| T purge precedence | A purge/finalize and purge/outbox barriers; H.`test_self_destruct_dispatch_survives_abort_and_notification_failures`; P key-first tests. |

## Reproduction and verification ledger

Final runtime implementation is pinned by the implementation commit above.
Documentation/evidence changes do not change the wheel runtime code. Preliminary
runs were used to reproduce failures, not substituted for final-wheel evidence.

| Gate | Linux | Native Windows |
| --- | --- | --- |
| Ruff check / format | Exit0; 322 files formatted | Exit0; 322 files formatted |
| Strict MyPy | Exit0; 293 source files | Exit0; 293 source files |
| Full unittest discovery | Exit0; **453 tests**, 99.487s, no skips | Exit0; **453 tests**, 314.727s, 2 documented skips |
| Structural boundary / central registry | Exit0 | Included in native full suite; direct quality checks also pass |
| Generated originals + two generations | Exit0, no drift | Exit0, no drift |
| Compatibility manifest | Exit0; no previous public release, current manifest is baseline | Same checked-in manifest |
| Clean developer install | Pinned dev dependencies; SDK/base/Terminal intentionally editable; pip check clean, Terminal discovered | Native full suite uses its explicit source path in an isolated pinned tooling venv; subsequent explicit editable SDK/base/Terminal install, pip check and metadata discovery pass; all 10 CLI contracts pass in 0.034s |

Authored canonical relative links resolve, and all 104 explicitly prefixed test names
in the trace tables resolve to their linked source methods. Repeated generation left
`docs/generated/` unchanged. The final scope diff leaves GUI/layout drafts untouched.

The native Windows skips are exactly:

1. `test_chat_contract.LivePushContentTests.test_input_handler_non_tty_stdin_exits_cleanly`:
   `termios TTY guard is POSIX-only; Windows input uses msvcrt`.
2. `test_session_auth_contract.SessionAuthContractTests.test_quick_unlock_rejects_unsafe_parent_and_oversized_metadata`:
   `POSIX permission bits do not define Windows ACLs.`

These existing platform guards are not new acceptance bypasses. Effective Windows
ACL create/replace/validate and unsafe-trustee rejection execute in the native
credential tests; the owner-only test now asserts ACLs on Windows and mode bits on
POSIX. The previously nondeterministic writer test executes on both hosts.

Final built-artifact matrix (all exit0 on native Linux and native Windows):

| Scenario | Observed acceptance result |
| --- | --- |
| SDK only | Site-packages client/DTO/proof/frontend imports and operations; no base/daemon/SQLCipher/dotenv imports or host path lookup. Strict good consumer succeeds; deliberately bad consumer fails with exactly three expected arg-type errors. |
| Base + SDK | CLI help/version, noninteractive daemon help and metadata-only inventory work without UI. Selecting missing Terminal returns safe exit2 before host bootstrap. |
| Base + SDK + non-shipped frontend | `FAKE_STARTED_BEFORE_HOST`, then `FAKE_DYNAMIC_IPC_OK`: installed entrypoint, base dispatcher, public deferred host, real dynamic-port IPC and snapshot; no Terminal imports or TTY. First-run/cancel/retry branches are additionally covered by the named public-host tests. |
| Base + SDK + Terminal | `TERMINAL_LOOP_HELP_REDRAW_OK`: real installed launcher, host, IPC bootstrap, chat loop, header and help render. Only hardware input construction/read is controlled (`/help`, `/clear`, `/help`, `/exit`); Chat.run, Renderer and host/SDK are not mocked. |
| Uninstall/reinstall | Removing Terminal preserves base CLI/SDK and removes its inventory entry; reinstall restores it; removing base + Terminal leaves working SDK. Pip check succeeds at every stage. |
| Actual ZIP installers | All three `linux-x86_64-py311` and all three `windows-x86_64-py311` archives execute their native offline sh/cmd installers. Explicit target, imports from the created venv, version, inventory and pip check pass. No implicit source import or network dependency fallback. |
| Ownership/RECORD | All six embedded Metor wheel copies per platform have valid RECORD membership/hash/size; no overlap between different distributions; SDK alone owns the five subpackage markers; superseded single-file implementations absent. Rebuilt copies across bundle variants contain identical namespace runtime bytes. |

The installed validators end with `ALL_ISOLATED_ARTIFACT_SCENARIOS_OK`; installer
logs contain three `NATIVE_OFFLINE_ZIP_OK` lines per host. The independent all-copy
RECORD audit emits twelve `WHEEL_RECORD_OWNERSHIP_OK` lines across both platforms.
`validate_wheel_versions.py <bundle-root>/*/wheelhouse/metor*.whl` succeeds for each
host and validates exact official dependency pins. Archive timestamps/build metadata
can differ; byte-identical whole wheels across separate builds are not claimed.

Representative wheel digests below are specifically the three wheels embedded in
each **Terminal bundle** (not ambiguously selected from several rebuilt copies).
The ZIP hashes pin every other embedded copy and the native installers as well.

| Host / Terminal-bundle wheel | Bytes | SHA256 |
| --- | --- | --- |
| Linux `metor-0.2.0-py3-none-any.whl` | 384876 | `cf164f7d22bf35da2bdd5b4c17cd80f51e61e4ac9d77ce5babb57227539ebbdc` |
| Linux `metor_sdk-0.2.0-py3-none-any.whl` | 73796 | `74160831c1b6ab5786671fb8e74c94f8ed744c2daee469b6995b6b462a4d851f` |
| Linux `metor_ui_terminal-0.2.0-py3-none-any.whl` | 60979 | `ed7ebfbe68652dac04110a80db24efe3bc6bdc05b2469ad3064e93c4bf3fd63c` |
| Windows `metor-0.2.0-py3-none-any.whl` | 384920 | `554d437bc0e93f728fdbd194dd7d8c5b7ac8a453414ef047be6838cab1dd0aa4` |
| Windows `metor_sdk-0.2.0-py3-none-any.whl` | 73800 | `3aa78d61c2dfc7f5e5e052711f129772b83b5c594b40a797692154c850863d15` |
| Windows `metor_ui_terminal-0.2.0-py3-none-any.whl` | 60988 | `517fc6464b53fbb23448bbf49377f099c561fc5d3214fd153b986e544a780ae4` |

| Native ZIP | SHA256 |
| --- | --- |
| `metor-sdk-wheelhouse-linux-x86_64-py311.zip` | `6d364f8f6a4d9aa6896363bbba133a8018d52892900fba6495f47f4e97a047ec` |
| `metor-wheelhouse-linux-x86_64-py311.zip` | `195fa97dea426735eef75fa733010427ff2550ec4b3841567843e91a91a353b1` |
| `metor-ui-terminal-wheelhouse-linux-x86_64-py311.zip` | `6006c0ca894d79372ca6fc0eece400812ea46f58ca36116d0de903d6f307cb4c` |
| `metor-sdk-wheelhouse-windows-x86_64-py311.zip` | `46d7f44cdaee860a8c0c294ec3acb0b1a798f321b618f57608a7d5cc21811b54` |
| `metor-wheelhouse-windows-x86_64-py311.zip` | `c8f6295f0df772f7b670b29ad6f7fe6494a2a5c1e986c8e73099f455f61875d8` |
| `metor-ui-terminal-wheelhouse-windows-x86_64-py311.zip` | `22270ed6f78eb671c6e94180e7b9fb5e54f87cf1ca8dcb1b2c6f38c9ce3a1053` |

Retained local transcripts (not portable repository artifacts) are under `/tmp/`:
`metor-closure-linux-final.log`, `metor-closure-windows-final.log`,
`metor-closure-artifacts-{linux,windows}.log`,
`metor-closure-offline-{linux,windows}.log`, `metor-closure-wheel-records.log`,
`metor-closure-generated-{linux,windows}.log`, `metor-closure-dev-install.log`,
`metor-closure-dev-windows.log`, `metor-closure-dev-windows-tests.log`.
Final bundles remain in `/tmp/metor-closure-bundles` and native
`C:\Users\lampl\AppData\Local\Temp\metor-closure-bundles-a2ydhyps`.
Temporary consumer/profile environments are cleaned by their context managers.

Native environments:

| Host | Interpreter/tools |
| --- | --- |
| Linux | WSL2 Linux `6.18.33.2-microsoft-standard-WSL2`, x86_64/glibc2.35; CPython3.11.4; fresh `/tmp/metor-closure-clean-dev` venv. |
| Windows | Native Windows `10.0.26200`, x86_64; native CPython3.11.4, isolated `metor-closure-native-a2ydhyps` venv; Windows PowerShell5.1.26100.9444. Not Wine or Linux `--platform win32`. |
| Both | Ruff0.15.8, MyPy1.19.1, setuptools80.10.2, wheel0.46.3, pip23.1.2, PyNaCl1.6.2. SQLCipher: Linux sqlcipher3-binary0.6.0; Windows sqlcipher3 0.6.2. Remaining dependencies exactly `requirements/dev.lock`. |

Fresh developer reproduction:

```console
python -m venv <temporary-dev-venv>
<venv-python> -m pip install -r requirements/dev.lock
<venv-python> -m pip install --no-deps --no-build-isolation -e packaging/sdk -e . -e packaging/terminal
<venv-python> -m pip check
<venv-metor> chat --list-uis
```

The last executable is `<venv>/bin/metor` on Linux or `<venv>/Scripts/metor.exe` on
Windows. Expected inventory is exactly `terminal  metor-ui-terminal` in this setup.
The recipe is not a base-only editable install relying on old entrypoint metadata.

Run using each host's native venv interpreter/tool executables, from the checkout:

```console
ruff check src/metor/ scripts/ tests/
ruff format --check src/metor/ scripts/ tests/
mypy src/metor/ scripts/
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/check_boundaries.py
python scripts/versioning.py validate
python scripts/validate_generated_docs.py
python scripts/check_release_compatibility.py --current docs/generated/compatibility.json
python scripts/build_release_wheelhouse.py --variant all --skip-pip-upgrade --output-dir <native-temporary-bundles>
python scripts/validate_installed_artifacts.py <native-temporary-bundles>
python scripts/validate_release_installers.py <native-temporary-bundles>
```

Source-wheel builds are serialized; they share setuptools' checkout build directory.
Consumer environments are temporary, non-editable, no PYTHONPATH/MYPYPATH, use
`-I` and working directories outside the checkout. The intentional wrong external
consumer must fail with three `arg-type` errors; zero errors would be a failed gate.
Every installation stage runs `pip check`. ZIP installers resolve only their bundled
dependencies with explicit SDK/base/Terminal targets and execute native sh/cmd paths.

Native reproduction observations: the initial Windows probe demonstrated empty
Target binding. After fixing that, create succeeded but replacement failed with
Set-Acl/SeSecurityPrivilege. The corrected DACL-only setter passed both create and
replace on Unicode/space paths. Raw helper output was inspected only in a temporary
test-key diagnostic; production errors expose phase/exit status, never stderr or
verifier/password/PIN. No failed native test was removed or Windows-skipped to pass.

## Public frontend integration map (no GUI implementation)

| Concern | Public binding and outcome |
| --- | --- |
| Launch | `metor.client.FRONTEND_LAUNCH_CONTRACT_VERSION == 2`; selected entrypoint receives `FrontendLaunchContext` with deferred `FrontendHost`. UI starts before its own interactions. |
| First run/retry/cancel | Host inspect/list/select/create and `bootstrap(interactions)`; `FrontendBootstrapError.reason` is machine-readable. Retry after missing profile, cancel, failed start or transient endpoint; concurrent attempt rejected. Each secret provider consumed at most once. |
| Endpoint | `FrontendBootstrapResult.port: int` resolves active local dynamic port or configured forwarded port. This is not authentication success: connect and bootstrap the SDK and handle transport/protocol/auth failures. Remote never starts local daemon. |
| Settings | `FrontendSettings`: client values and validated client/UI writes, registered Terminal UI values, narrowly named daemon presentation hints. Base owns filesystem/profile cascade and official metadata. No Config/ProfileManager/Data facade in frontend. |
| Profile switching | `ProfileRuntimeCoordinator` with a client factory built through public host results; typed `ProfileSwitchError`/phase/source_released, candidate unpublished until bootstrap/snapshot succeeds. No implicit new LIVE reconnect on return. |
| Events/results | `MetorClient` callback receives async and correlated nonterminal progress once; terminal typed result belongs to caller. Rejection, protocol error, timeout and loss are distinct. Request leases are transport-generation scoped; no silent replay into replacement. |
| Snapshot | Epoch/revision govern state deltas, not suppression of correlated command results or media chunks. Get fresh snapshot after loss/resync. Bounded queues explicitly signal loss rather than silent accepted-event omission. |
| Retained media | Discover via retained inventory; bounded reads are non-consuming; explicit release owns deletion. Direction/delivery/identity remain exact. Draft commit/cancel is separate from delivery ACK. |
| Restricted context | Daemon enforces frozen logical context and turn provenance for feedback/read/release; transport recovery may preserve context, new same-peer call cannot. Anonymous handles identify one pending request, not an onion lifetime. |
| Purge | Prior runtime/session-scoped lifecycle authority required. `daemon.self_destruct_requires_unlock` defaults true; false relaxes only additional reauthorization, never creates authority. Key destruction, runtime release and filesystem cleanup have distinct outcomes; lost socket alone means unknown outcome. |

## Limitations and stop point

- Hosted GitHub Actions for these unpushed commits: **UV**, not fabricated CI success.
  The CI workflow now runs native quality, freshness, offline bundles, external
  typing, isolated consumers and actual installers on both OS jobs. The reviewed
  run `34639912907` remains historical failing Windows evidence, not this revision.
- Controlled Tor is used for local integration. Actual Tor-network latency,
  production peers, physical microphones/speakers and device permissions are UV
  and outside this repair assignment. No hardware/GUI acceptance is claimed.
- Arbitrary user callbacks cannot be forcibly cancelled. Managed generation/thread
  resources are bounded and old callback authority is isolated; reconnect may fail
  admission while the configured blocked-generation bound is exhausted.
- Python mutable-memory clearing/file overwrite are best effort. No physical-erasure
  or unconditional anti-spoofing guarantee is asserted.
- Stop here before GUI implementation. The owner separately accepts the foundation,
  functional GUI spec and layout spec before a later GUI workstream.

## Remaining closure R01–R03 — 12 September 2026

Reviewed baseline: `1d21dcd8989bc0f98af624a4b6865fe4bd06ac7b`.
Reconciled implementation parent: `c90e3ddcd167472e2838f7eba724c6cf88f3f63d`.
The newer owner commit changed documentation only. No branch reset, GUI work,
GUI specification edits, governance cleanup or `docs/.temp` edits were performed.

### Focused traceability and ownership

- **R01:** ordinary authenticated RejectCommand now transfers final REJECT delivery
  to the existing bounded FIFO writer, with the configured finite final deadline.
  Queue saturation and oversized final admission cancel the exact transport safely.
- **R02:** StateTracker owns explicit exact-descriptor retirement. Remote/stale/
  replacement/failure/abort paths cancel registered workers, and only their exit
  callback removes registry ownership. Weak tombstones prevent admission between
  cancellation and physical closure without retaining retired descriptors forever.
  Local final admission is atomic with receiver cleanup; duplicate finish is
  idempotent, late enqueue cannot cancel the final frame, and receiver cleanup
  preserves admitted final drains. Physical socket I/O and cancellation remain
  outside the canonical state lock; idle workers are not automatically retired.
  Local-termination markers are weak so absent receivers do not leak descriptors.
  The teardown audit includes active/pending replacement, outbound handshake failure,
  pending expiry, receiver cleanup, listener rejection, dedicated DROP teardown and
  destructive shutdown. Listener/DROP explicit rejection uses final drain as well.
- **R03:** four scoped Git attributes establish LF checkout bytes. Canonical
  generators already wrote UTF-8/LF; no semantic generated change was needed.
  Shared CI installs Node22.17.1 and lockfile Prettier3.8.1. Generators invoke that
  local pinned formatter, fail on unavailable/mismatched/failed tooling, and never
  download an unpinned formatter or silently skip formatting. Original freshness and
  second-pass determinism remain exact byte comparisons with separate diagnostics.

The existing writer/state ownership boundaries remain intact; no broad refactor,
distribution, API, storage schema or compatibility-axis bump is warranted. Narrow
teardown delegation in the larger modules avoids splitting the existing session
state machine. Older test doubles gained the new retirement/shutdown interface;
no existing security or behavior assertions were removed or relaxed.

### Baseline reproductions

Before production edits, `test_remaining_closure_contract.py` ran four enclosing
transport tests on the reconciled unchanged runtime: **15 failures**, including
ordinary REJECT receiving empty bytes before EOF, all twelve remote DISCONNECT/EOF
cycles retaining workers, and active/pending replacement retaining workers.
The queue-saturation case already cancelled successfully. Log:
`/tmp/metor-r01-r02-red.log`.

Native Windows Git cloned the public repository into
`C:\Users\lampl\AppData\Local\Temp\metor-r03-native-zrjwy57r`,
checked out detached reviewed SHA, with `core.autocrlf=true`. Native CPython3.11.4,
Node22.17.0 and actual `npx --no-install prettier --version` **3.9.6** were observed.
The baseline's npx invocation was therefore not using the repository's pinned3.8.1.
Nevertheless its output exactly matched canonical LF bytes: formatter version drift
did not cause semantic differences in this reproduction.

| Artifact | Original bytes / CRLF count | First bytes / CRLF count | First SHA256 (also second) |
| --- | --- | --- | --- |
| API.md | 144162 / 5402 | 138760 / 0 | `9302122efe66ac9cdce6bba1fe28d7c645d4cf1b65e4177b6af2a46ab7589467` |
| SETTINGS.md | 51929 / 1105 | 50824 / 0 | `45de92494d0b34cbdea4c1418fcf9f3dfb68734952fb76f0a5da8d4960c06cbd` |
| api.schema.json | 215482 / 10318 | 205164 / 0 | `45b762505a11fdc3357fb267496ed587ce35035a5baebb081b11e0d288be67a5` |
| compatibility.json | 274631 / 11043 | 263588 / 0 | `09ebaa248d89903174ab21efa6bf9bd8ca19212e2a81cc02668b06511ef54a26` |

All four: original != first; first == second; original CRLF→LF conversion == first;
no UTF-8 BOM. Normalization was used only to diagnose, never to accept a validation
result. Raw diagnostic log: `/tmp/metor-r03-native-original.log`.
The new regression deliberately changes a JSON generation value and requires exit1,
separately exercises a nondeterministic second pass, and rejects CRLF drift too.

### Verification commands and result ledger

```console
npm ci
python -m unittest discover -s tests -p 'test_*closure*.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
ruff check src/metor/ scripts/ tests/
ruff format --check src/metor/ scripts/ tests/
mypy src/metor/ scripts/
python -m pip check
python scripts/check_boundaries.py
python scripts/versioning.py validate
python scripts/validate_generated_docs.py
python scripts/build_release_wheelhouse.py --variant all --skip-pip-upgrade --output-dir <bundles>
python scripts/validate_wheel_versions.py <bundles>/*/wheelhouse/metor*.whl
python scripts/validate_installed_artifacts.py <bundles>
python scripts/validate_release_installers.py <bundles>
```

Initial focused suite: **38 tests passed**, 32.829s. Final full-suite, native fresh
checkout, artifact and hosted CI results will be appended after completion.
Historical failed CI remains run `34651975594`, attempt2, Windows job
`103437618588`; its skipped artifact gate is not counted as passing.

Stop before GUI implementation. Independent approval remains the owner's review.
