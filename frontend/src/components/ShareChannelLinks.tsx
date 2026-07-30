interface ShareChannelLinksProps {
  url: string;
  text?: string;
}

function GmailIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-3.5 w-3.5">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path strokeLinecap="round" strokeLinejoin="round" d="m4 6.5 8 6 8-6" />
    </svg>
  );
}

function WhatsAppIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
      <path d="M12 2a10 10 0 0 0-8.6 15L2 22l5.2-1.4A10 10 0 1 0 12 2Zm0 2a8 8 0 0 1 6.9 12l1.9-.5-1.9.5.2-.2A8 8 0 1 1 12 4Zm-3.1 3.9c-.2 0-.5 0-.7.3-.3.3-1 1-1 2.3s1 2.7 1.1 2.8c.1.2 2 3 4.7 4.2 2.3 1 2.8.8 3.3.8.5-.1 1.6-.6 1.8-1.3.2-.6.2-1.1.1-1.2-.1-.2-.3-.3-.6-.4l-1.7-.8c-.2-.1-.4-.2-.6.1l-.6 1c-.1.2-.3.2-.5.1-.3-.1-1.1-.4-2.1-1.3-.8-.7-1.3-1.6-1.5-1.9-.1-.2 0-.4.1-.5l.4-.5c.1-.2.2-.3.2-.5.1-.2 0-.4 0-.5l-.7-1.7c-.2-.4-.4-.4-.6-.4Z" />
    </svg>
  );
}

function FacebookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
      <path d="M13.5 21v-7.6h2.6l.4-3h-3v-1.9c0-.9.2-1.5 1.5-1.5h1.6V4.1C15.9 4 15 4 13.9 4c-2.2 0-3.7 1.3-3.7 3.8v2.1H7.6v3h2.6V21h3.3Z" />
    </svg>
  );
}

export function ShareChannelLinks({ url, text }: ShareChannelLinksProps) {
  const shareBody = text ? `${text}\n${url}` : url;
  const encodedUrl = encodeURIComponent(url);
  const encodedBody = encodeURIComponent(shareBody);
  const subject = encodeURIComponent(text ? `Talk2DB result: ${text}` : "Talk2DB shared result");

  const channels = [
    {
      name: "Gmail",
      href: `https://mail.google.com/mail/?view=cm&fs=1&tf=1&su=${subject}&body=${encodedBody}`,
      icon: <GmailIcon />,
    },
    { name: "WhatsApp", href: `https://wa.me/?text=${encodedBody}`, icon: <WhatsAppIcon /> },
    { name: "Facebook", href: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`, icon: <FacebookIcon /> },
  ];

  return (
    <div className="flex items-center gap-1">
      {channels.map((c) => (
        <a
          key={c.name}
          href={c.href}
          target="_blank"
          rel="noopener noreferrer"
          title={`Share via ${c.name}`}
          className="flex h-6 w-6 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        >
          {c.icon}
        </a>
      ))}
    </div>
  );
}
