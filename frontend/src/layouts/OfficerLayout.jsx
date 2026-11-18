import { Outlet } from 'react-router-dom';
import PrototypeNotice from '../components/shared/PrototypeNotice.jsx';

export default function OfficerLayout() {
  return <><PrototypeNotice /><Outlet /></>;
}

