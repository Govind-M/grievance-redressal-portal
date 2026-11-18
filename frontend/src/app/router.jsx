import PublicLayout from '../layouts/PublicLayout.jsx';
import CitizenLayout from '../layouts/CitizenLayout.jsx';
import CMOLayout from '../layouts/CMOLayout.jsx';
import OfficerLayout from '../layouts/OfficerLayout.jsx';
import ModulePlaceholder from '../components/shared/ModulePlaceholder.jsx';

// Development placeholders are public. Real authentication and guards arrive in Phase 2.
export const publicPages = [
  ['/', 'Home'], ['/about', 'About Us'], ['/how-it-works', 'How It Works'],
  ['/departments', 'Departments'], ['/contact', 'Contact Us'], ['/faq', 'FAQ'],
];

export const routes = [
  {
    element: <PublicLayout />,
    children: [
      ...publicPages.map(([path, title]) => ({
        path, element: <ModulePlaceholder title={title} />,
      })),
      { path: '*', element: <ModulePlaceholder title="Page not found" /> },
    ],
  },
  { path: '/citizen', element: <CitizenLayout />, children: [
    { path: 'dashboard', element: <ModulePlaceholder title="Citizen Dashboard" /> },
  ] },
  { path: '/cmo', element: <CMOLayout />, children: [
    { path: 'dashboard', element: <ModulePlaceholder title="CMO Dashboard" /> },
  ] },
  { path: '/officer', element: <OfficerLayout />, children: [
    { path: 'dashboard', element: <ModulePlaceholder title="Officer Dashboard" /> },
  ] },
];

