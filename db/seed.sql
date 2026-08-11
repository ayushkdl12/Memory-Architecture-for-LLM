-- ============================================================================
-- Demo seed data for memory_db  (personal knowledge graph of "Aarav Thapa")
-- One user, 3 chat sessions, 11 dialogue turns, 9 extracted memory atoms
-- (with one temporal update: employer Fusemachines -> LeapFrog Technology),
-- plus retention/retrieval audit rows, one media item, one document + chunks,
-- and one web-search log. Run AFTER db/schema.sql.
-- Source: seed_data.json (same directory).
-- ============================================================================

BEGIN;

INSERT INTO users (user_id, name, created_at) VALUES
('00000000-0000-0000-0000-000000000001', 'Aarav Thapa', '2026-07-01T09:00:00Z');

INSERT INTO chat_sessions (session_id, user_id, title, created_at) VALUES
('22222222-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Onboarding chat',       '2026-07-01T09:02:00Z'),
('22222222-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Trip planning',         '2026-07-14T18:20:00Z'),
('22222222-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Follow-up: job change', '2026-08-05T11:10:00Z');

INSERT INTO messages (message_id, session_id, role, content, created_at) VALUES
('33333333-0000-0000-0000-000000000001', '22222222-0000-0000-0000-000000000001', 'user',      'Hi, I''m Aarav. I work as a backend engineer at Fusemachines in Kathmandu.', '2026-07-01T09:02:10Z'),
('33333333-0000-0000-0000-000000000002', '22222222-0000-0000-0000-000000000001', 'assistant', 'Nice to meet you, Aarav! I''ve noted that you''re a backend engineer at Fusemachines in Kathmandu.', '2026-07-01T09:02:14Z'),
('33333333-0000-0000-0000-000000000003', '22222222-0000-0000-0000-000000000001', 'user',      'I prefer Python over Java, and I''m vegetarian.', '2026-07-01T09:03:40Z'),
('33333333-0000-0000-0000-000000000004', '22222222-0000-0000-0000-000000000001', 'assistant', 'Got it -- Python preferred over Java, and vegetarian diet.', '2026-07-01T09:03:44Z'),
('33333333-0000-0000-0000-000000000010', '22222222-0000-0000-0000-000000000002', 'user',      'I''m planning a trip to Pokhara next month, goal is to finish it by end of August.', '2026-07-14T18:20:30Z'),
('33333333-0000-0000-0000-000000000011', '22222222-0000-0000-0000-000000000002', 'assistant', 'Noted -- trip to Pokhara, target completion end of August 2026.', '2026-07-14T18:20:35Z'),
('33333333-0000-0000-0000-000000000012', '22222222-0000-0000-0000-000000000002', 'user',      'Also, never book me a window seat, I get motion sick.', '2026-07-14T18:22:00Z'),
('33333333-0000-0000-0000-000000000013', '22222222-0000-0000-0000-000000000002', 'assistant', 'Understood -- no window seats, ever. I''ll treat that as a standing rule.', '2026-07-14T18:22:05Z'),
('33333333-0000-0000-0000-000000000014', '22222222-0000-0000-0000-000000000002', 'user',      'Attended the Nepal AI Summit 2026 in Pokhara last week, it was great.', '2026-07-14T18:25:00Z'),
('33333333-0000-0000-0000-000000000020', '22222222-0000-0000-0000-000000000003', 'user',      'Update: I actually left Fusemachines. I''m now a backend engineer at LeapFrog Technology.', '2026-08-05T11:10:20Z'),
('33333333-0000-0000-0000-000000000021', '22222222-0000-0000-0000-000000000003', 'assistant', 'Thanks for letting me know -- I''ve updated your employer to LeapFrog Technology and archived the old record.', '2026-08-05T11:10:25Z');

INSERT INTO memory_atoms
(memory_id, user_id, session_id, source_message_id, memory_type, category, subject, attribute, value, content, priority, confidence_score, is_confirmed, is_pinned, is_active, retention_status, valid_from, valid_until, expires_at) VALUES
('44444444-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000001','FACT','employment','user','employer','Fusemachines','User works as a backend engineer at Fusemachines in Kathmandu.','HIGH',0.95,true,false,false,'ARCHIVED','2026-07-01T09:02:10Z','2026-08-05T11:10:20Z',NULL),
('44444444-0000-0000-0000-000000000102','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000001','FACT','employment','user','job_title','Backend Engineer','User''s job title is Backend Engineer.','MEDIUM',0.95,true,false,true,'ACTIVE','2026-07-01T09:02:10Z',NULL,NULL),
('44444444-0000-0000-0000-000000000103','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000001','FACT','location','user','city','Kathmandu','User is based in Kathmandu.','MEDIUM',0.9,true,false,true,'ACTIVE','2026-07-01T09:02:10Z',NULL,NULL),
('44444444-0000-0000-0000-000000000104','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000003','PREFERENCE','tech','user','language_preference','Python over Java','User prefers Python over Java.','LOW',0.85,true,false,true,'ACTIVE','2026-07-01T09:03:40Z',NULL,NULL),
('44444444-0000-0000-0000-000000000105','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000003','PREFERENCE','diet','user','diet','vegetarian','User is vegetarian.','HIGH',0.95,true,true,true,'ACTIVE','2026-07-01T09:03:40Z',NULL,NULL),
('44444444-0000-0000-0000-000000000110','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000002','33333333-0000-0000-0000-000000000010','GOAL','travel','user','trip_to_pokhara','complete by 2026-08-31','User wants to complete a trip to Pokhara by end of August 2026.','MEDIUM',0.9,true,false,true,'ACTIVE','2026-07-14T18:20:30Z',NULL,'2026-08-31T23:59:59Z'),
('44444444-0000-0000-0000-000000000111','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000002','33333333-0000-0000-0000-000000000012','RULE','travel','user','seat_preference','never window seat','Never book a window seat for the user -- causes motion sickness.','CRITICAL',0.98,true,true,true,'ACTIVE','2026-07-14T18:22:00Z',NULL,NULL),
('44444444-0000-0000-0000-000000000112','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000002','33333333-0000-0000-0000-000000000014','EVENT','travel','user','attended_event','Nepal AI Summit 2026, Pokhara','User attended the Nepal AI Summit 2026 in Pokhara.','LOW',0.9,false,false,true,'ACTIVE','2026-07-14T18:25:00Z',NULL,NULL),
('44444444-0000-0000-0000-000000000120','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000003','33333333-0000-0000-0000-000000000020','FACT','employment','user','employer','LeapFrog Technology','User now works at LeapFrog Technology as a backend engineer.','HIGH',0.95,true,false,true,'ACTIVE','2026-08-05T11:10:20Z',NULL,NULL);

INSERT INTO fact_versions (version_id, user_id, subject, attribute, old_memory_id, new_memory_id, changed_at, change_reason) VALUES
('55555555-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000001','user','employer','44444444-0000-0000-0000-000000000101','44444444-0000-0000-0000-000000000120','2026-08-05T11:10:20Z','User reported changing employer.');

INSERT INTO retention_logs (retention_id, memory_id, action, reason, score, created_at) VALUES
('66666666-0000-0000-0000-000000000301','44444444-0000-0000-0000-000000000101','ARCHIVE','Superseded by new employer fact.',0.0,'2026-08-05T11:10:20Z'),
('66666666-0000-0000-0000-000000000302','44444444-0000-0000-0000-000000000105','KEEP','Pinned dietary preference -- exempt from sweep.',0.9,'2026-08-05T12:00:00Z');

INSERT INTO retrieval_logs (retrieval_id, session_id, message_id, query_text, retrieved_memory_ids, retrieval_reason, created_at) VALUES
('77777777-0000-0000-0000-000000000401','22222222-0000-0000-0000-000000000002','33333333-0000-0000-0000-000000000010','user travel preferences and constraints','["44444444-0000-0000-0000-000000000111","44444444-0000-0000-0000-000000000110"]','Trip-planning context needed seat rule and active travel goal.','2026-07-14T18:20:31Z'),
('77777777-0000-0000-0000-000000000402','22222222-0000-0000-0000-000000000003','33333333-0000-0000-0000-000000000020','user employer','["44444444-0000-0000-0000-000000000101"]','Detecting possible fact update before writing new atom.','2026-08-05T11:10:21Z');

INSERT INTO media (media_id, user_id, session_id, source_message_id, memory_id, filename, url, mime_type, description, created_at) VALUES
('88888888-0000-0000-0000-000000000501','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000002','33333333-0000-0000-0000-000000000014','44444444-0000-0000-0000-000000000112','summit_badge.jpg','https://cdn.example.com/u-1001/summit_badge.jpg','image/jpeg','Conference badge photo, Nepal AI Summit 2026','2026-07-14T18:26:00Z');

INSERT INTO documents (doc_id, user_id, session_id, filename, mime_type, char_count, preview, created_at) VALUES
('99999999-0000-0000-0000-000000000601','00000000-0000-0000-0000-000000000001','22222222-0000-0000-0000-000000000001','resume_aarav.pdf','application/pdf',118,'Aarav Thapa -- Backend Engineer. 4 years experience with Python, PostgreSQL, distributed systems...','2026-07-01T09:05:00Z');

INSERT INTO document_chunks (chunk_id, doc_id, chunk_index, text, created_at) VALUES
('aaaaaaaa-0000-0000-0000-000000000701','99999999-0000-0000-0000-000000000601',0,'Aarav Thapa -- Backend Engineer. 4 years experience with Python, PostgreSQL, distributed systems.','2026-07-01T09:05:01Z'),
('aaaaaaaa-0000-0000-0000-000000000702','99999999-0000-0000-0000-000000000601',1,'Previously at Fusemachines (2023-2026); currently transitioning to LeapFrog Technology.','2026-07-01T09:05:01Z');

INSERT INTO search_logs (search_id, session_id, message_id, query_text, provider, results, created_at) VALUES
('bbbbbbbb-0000-0000-0000-000000000801','22222222-0000-0000-0000-000000000002','33333333-0000-0000-0000-000000000010','best time to visit Pokhara Nepal','web_search','[{"title":"Pokhara travel guide","url":"https://example.com/pokhara-guide"}]','2026-07-14T18:20:40Z');

INSERT INTO user_settings (user_id, custom_instructions, updated_at) VALUES
('00000000-0000-0000-0000-000000000001','Keep responses concise. Never suggest window seats when booking travel.','2026-07-14T18:22:10Z');

COMMIT;