-- One profile row per account, created automatically at sign-up.
-- Row-Level Security: people can read and edit only their own profile.

create table if not exists public.profiles (
  id              uuid primary key references auth.users (id) on delete cascade,
  full_name       text check (char_length(full_name) <= 80),
  avatar_url      text,
  github_username text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "Read own profile"
  on public.profiles for select to authenticated
  using ((select auth.uid()) = id);

create policy "Update own profile"
  on public.profiles for update to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

-- No insert or delete policies on purpose: the trigger below creates rows,
-- and deleting the auth user deletes the profile (on delete cascade).

-- Copy the name and avatar from the sign-up form, GitHub or Google.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, full_name, avatar_url, github_username)
  values (
    new.id,
    left(coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'), 80),
    new.raw_user_meta_data ->> 'avatar_url',
    case when new.raw_app_meta_data ->> 'provider' = 'github'
         then new.raw_user_meta_data ->> 'user_name' end
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Keep updated_at honest.
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
  before update on public.profiles
  for each row execute function public.touch_updated_at();
