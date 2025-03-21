import React from "react";
import { Navbar, Nav, Container } from "react-bootstrap";

const AppNavbar: React.FC = () => {
    return (
        <Navbar bg="light" variant="light" expand="lg">
            <Container>
                <Navbar.Brand href="/">DigSiViz</Navbar.Brand>
                <Navbar.Toggle aria-controls="basic-navbar-nav" />
                <Navbar.Collapse id="basic-navbar-nav">
                    <Nav className="me-auto">
                        <Nav.Link href="/">Home</Nav.Link>
                        <Nav.Link href="/clabinfo">ContainerLab Info</Nav.Link>
                        <Nav.Link href="/websocket">Websocket Test</Nav.Link>
                        <Nav.Link href="/topology">Topology</Nav.Link>
                    </Nav>
                </Navbar.Collapse>
            </Container>
        </Navbar>
    );
};

export default AppNavbar;
