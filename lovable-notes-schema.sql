CREATE TABLE public.notes (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    title text NOT NULL DEFAULT ''::text,
    body text NOT NULL DEFAULT ''::text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT notes_pkey PRIMARY KEY (id),
    CONSTRAINT notes_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

GRANT ALL ON TABLE public.notes TO anon;
GRANT ALL ON TABLE public.notes TO authenticated;
GRANT ALL ON TABLE public.notes TO service_role;

ALTER TABLE public.notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own notes"
ON public.notes
FOR ALL
TO authenticated
USING ((auth.uid() = user_id))
WITH CHECK ((auth.uid() = user_id));
