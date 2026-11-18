import { useRoutes } from 'react-router-dom';
import { routes } from './app/router.jsx';

export default function App() {
  return useRoutes(routes);
}

