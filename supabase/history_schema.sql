-- Run this in Supabase SQL Editor before setting HISTORY_BACKEND=supabase.
create extension if not exists pgcrypto;

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  owner_id text not null,
  title text not null default '新しい相談',
  context_turns integer not null default 0,
  context_epoch integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table public.conversations
  add column if not exists deleted_at timestamptz;

create index if not exists conversations_owner_updated_idx
  on public.conversations (owner_id, updated_at desc);

create table if not exists public.messages (
  id bigint generated always as identity primary key,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  owner_id text not null,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  context_epoch integer not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists messages_conversation_created_idx
  on public.messages (conversation_id, created_at, id);

-- This first scaffold uses the server-side REST adapter.
-- Enable RLS and replace these policies with auth.uid()-based policies
-- before exposing Supabase directly to end users.
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
