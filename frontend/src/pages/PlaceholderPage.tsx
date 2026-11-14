interface PlaceholderPageProps {
  title: string
  phase: number
}

/** Página provisional: solo el título y la fase en la que llega. */
export function PlaceholderPage({ title, phase }: PlaceholderPageProps) {
  return (
    <>
      <h1 className="page-title">{title}</h1>
      <p className="muted">Disponible en la fase {phase}</p>
    </>
  )
}
