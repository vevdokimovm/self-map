import { NavLink } from "react-router-dom";

export default function Nav() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? "nav__link active" : "nav__link";

  return (
    <nav className="nav">
      <span className="nav__brand">Карта себя</span>
      <NavLink to="/" end className={linkClass}>
        Разделы
      </NavLink>
      <NavLink to="/registry" className={linkClass}>
        Реестр фактов
      </NavLink>
      <NavLink to="/search" className={linkClass}>
        Поиск
      </NavLink>
    </nav>
  );
}
