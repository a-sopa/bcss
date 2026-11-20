/** The team shown in the "About us" popup. Photos live in public/team/, named after the GitHub username. */
export type Member = {
  name: string;
  github: string; // username, without the URL
  funFact?: string;
};

export const TEAM: Member[] = [
  { name: "Afonso Sopa", github: "a-sopa" },
  { name: "Diogo Osório", github: "dioooogooo" },
  { name: "Diogo Pinto", github: "diogofpinto" },
  { name: "Francisco Pereira", github: "franciscoppereira256" },
  { name: "Manuel André", github: "manuelamma" },
];

export const photoOf = (member: Member) => `./team/${member.github}.webp?v=2`;
