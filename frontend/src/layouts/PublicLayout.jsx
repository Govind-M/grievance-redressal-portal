import { Outlet } from 'react-router-dom';
import PrototypeNotice from '../components/shared/PrototypeNotice.jsx';

export default function PublicLayout() {
  return <><PrototypeNotice /><Outlet /></>;
}

